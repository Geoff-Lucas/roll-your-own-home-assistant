"""Hands-free activation: listening for "Hey Jarvis".

An always-on background task holds the microphone open and feeds it, 80 ms at
a time, to a small local model (openWakeWord's `hey_jarvis`). The audio is only
ever compared against that model and discarded — nothing is recorded or
recognized until the phrase is heard. Costs about 3 ms of CPU per frame.

The microphone can only be opened by one thing at a time, so on a detection the
listener lets go of it *before* calling `on_wake` (which starts an ordinary
tap-to-talk style interaction), and stays paused until that interaction is
over — see VoiceSession, which pauses and resumes it.
"""

import asyncio
import logging
import os
import time
from collections import deque
from typing import Awaitable, Callable, Optional, Protocol

from ..config import settings
from .recorder import MicUnavailable, rms

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # 80 ms: what the model is designed to be fed
FRAME_BYTES = FRAME_SAMPLES * 2
MODEL_NAME = "hey_jarvis_v0.1"
PHRASE = "Hey Jarvis"
_RETRY_SECONDS = 10.0  # when the microphone isn't there, look again this often


def _now() -> float:
    # A function (not time.monotonic directly) so tests can move this clock
    # without also moving the event loop's own.
    return time.monotonic()


class Stream(Protocol):
    async def readexactly(self, n: int) -> bytes: ...
    async def close(self) -> None: ...


class ArecordStream:
    """Raw 16 kHz mono PCM from the configured microphone, via arecord."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process

    @classmethod
    async def open(cls) -> "ArecordStream":
        command = [
            "arecord", "-q", "-D", settings.mic_device, "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1", "-t", "raw",
        ]  # fmt: skip
        try:
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError as exc:
            raise MicUnavailable("The wake word needs arecord, which isn't installed (alsa-utils)") from exc
        return cls(process)

    async def readexactly(self, n: int) -> bytes:
        try:
            return await asyncio.wait_for(self._process.stdout.readexactly(n), timeout=2.0)
        except asyncio.IncompleteReadError as exc:
            detail = (await self._process.stderr.read()).decode(errors="replace").strip()
            raise MicUnavailable(detail or "The microphone stopped responding") from exc
        except asyncio.TimeoutError as exc:
            raise MicUnavailable("The microphone isn't sending any audio") from exc

    async def close(self) -> None:
        if self._process.returncode is None:
            self._process.kill()
        await self._process.wait()


class OpenWakeWordDetector:
    """Scores a frame of audio: how likely is it that "Hey Jarvis" was just said?"""

    def __init__(self) -> None:
        self._model = None

    @staticmethod
    def model_path() -> str:
        import openwakeword

        return os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models", f"{MODEL_NAME}.onnx")

    def status(self) -> tuple[bool, str]:
        try:
            path = self.model_path()
        except ImportError:
            return False, "The wake word needs the openwakeword package (pip install -r requirements.txt)."
        if not os.path.exists(path):
            return False, f"The wake-word model {MODEL_NAME} wasn't found at {path}."
        return True, "ready"

    def _load(self):
        if self._model is None:
            from openwakeword.model import Model

            self._model = Model(wakeword_model_paths=[self.model_path()])
        return self._model

    def score(self, frame: bytes) -> float:
        import numpy as np

        scores = self._load().predict(np.frombuffer(frame, dtype=np.int16))
        return float(max(scores.values())) if scores else 0.0

    def reset(self) -> None:
        if self._model is not None:
            self._model.reset()


class WakeWordListener:
    phrase = PHRASE

    def __init__(
        self,
        *,
        detector,
        on_wake: Callable[[], Awaitable[None]],
        open_stream: Callable[[], Awaitable[Stream]] = ArecordStream.open,
        threshold: Optional[float] = None,
        cooldown: Optional[float] = None,
    ) -> None:
        self._detector = detector
        self._on_wake = on_wake
        self._open_stream = open_stream
        self.threshold = settings.voice_wakeword_threshold if threshold is None else threshold
        self.cooldown = settings.voice_wakeword_cooldown_seconds if cooldown is None else cooldown
        self._active = asyncio.Event()
        self._active.set()
        self._mic_open = False
        self._quiet_until = 0.0
        self._warned = False
        self.last_score = 0.0
        # What it has been hearing lately (~10 s of frames): the loudest level and
        # the best wake-word score. Exposed so "why didn't it wake?" can be
        # answered — is the microphone hearing anything, and how close did it get?
        self._recent: deque[tuple[float, float]] = deque(maxlen=125)

    @property
    def listening(self) -> bool:
        return self._mic_open

    @property
    def recent_peak_score(self) -> float:
        return max((score for score, _ in self._recent), default=0.0)

    @property
    def recent_peak_level(self) -> float:
        return max((level for _, level in self._recent), default=0.0)

    async def pause(self) -> None:
        """Stop listening and wait until the microphone has really been released."""
        self._active.clear()
        for _ in range(60):  # up to 3 seconds
            if not self._mic_open:
                return
            await asyncio.sleep(0.05)
        logger.warning("The wake-word listener didn't release the microphone in time")

    def resume(self) -> None:
        self._active.set()

    async def run(self) -> None:
        while True:
            await self._active.wait()
            try:
                heard = await self._listen()
            except asyncio.CancelledError:
                raise
            except MicUnavailable as exc:
                if not self._warned:  # once, not every retry
                    logger.warning("Wake word paused: %s (retrying every %ds)", exc, int(_RETRY_SECONDS))
                    self._warned = True
                await asyncio.sleep(_RETRY_SECONDS)
                continue
            except Exception:
                logger.exception("Wake-word listening failed")
                await asyncio.sleep(5)
                continue
            self._warned = False
            if heard:
                try:
                    await self._on_wake()
                except Exception:
                    logger.exception("Couldn't start listening after the wake word")

    async def _listen(self) -> bool:
        """Listen until the phrase is heard (True) or we're paused (False).
        The microphone is closed again before this returns either way."""
        stream = await self._open_stream()
        self._mic_open = True
        try:
            self._detector.reset()
            while self._active.is_set():
                frame = await stream.readexactly(FRAME_BYTES)
                self.last_score = await asyncio.to_thread(self._detector.score, frame)
                self._recent.append((self.last_score, rms(frame)))
                if self.last_score >= self.threshold and _now() >= self._quiet_until:
                    self._quiet_until = _now() + self.cooldown
                    logger.info("Heard %r (score %.2f)", PHRASE, self.last_score)
                    return True
            return False
        finally:
            await stream.close()
            self._mic_open = False
