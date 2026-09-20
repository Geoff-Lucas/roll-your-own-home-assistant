"""Capturing speech from the microphone, and knowing when the person is done.

Audio comes from `arecord` (part of alsa-utils, already needed for playback)
as raw 16 kHz mono PCM — no Python audio library, so nothing extra to build for
this machine. Recording stops on its own when speech has been followed by a
short silence, when nobody says anything, at a hard time limit, or when told to.
Nothing is written to disk; the audio exists only in memory until it has been
transcribed.
"""

import array
import asyncio
import math
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

from ..config import settings

SAMPLE_RATE = 16000
CHUNK_SECONDS = 0.16
CHUNK_BYTES = int(SAMPLE_RATE * CHUNK_SECONDS) * 2  # 16-bit samples
MIN_SPEECH_SECONDS = 0.4  # anything shorter is a tap on the desk, not a command


class MicUnavailable(RuntimeError):
    """The microphone can't be used (no arecord, wrong device, or it went quiet)."""


def rms(chunk: bytes) -> float:
    """Root-mean-square loudness of 16-bit little-endian samples."""
    samples = array.array("h")
    samples.frombytes(chunk[: len(chunk) // 2 * 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class EndpointDetector:
    """Watches loudness chunk by chunk and says when a spoken command has ended.

    A plain energy detector, tuned for a kitchen: "loud" means clearly above the
    quietest recent moment (the room's noise floor), and the bar is frozen at
    the level speech began so a softly-trailing sentence isn't cut off. It is
    deliberately simple; a proper voice-activity model can replace it later
    without touching anything else.
    """

    def __init__(
        self,
        *,
        silence_seconds: float,
        start_timeout: float,
        max_seconds: float,
        chunk_seconds: float = CHUNK_SECONDS,
        min_rms: float = 250.0,
        floor_cap: float = 400.0,
        ratio: float = 3.0,
    ):
        self.silence_seconds = silence_seconds
        self.start_timeout = start_timeout
        self.max_seconds = max_seconds
        self.chunk = chunk_seconds
        self.min_rms = min_rms
        self.floor_cap = floor_cap
        self.ratio = ratio
        self.elapsed = 0.0
        self.speaking = False
        self._recent: deque[float] = deque(maxlen=40)
        self._loud_run = 0
        self._quiet_for = 0.0
        self._hold = 0.0

    def feed(self, level: float) -> Optional[str]:
        """Returns None to carry on, or why to stop: "done", "no_speech" or "max"."""
        self.elapsed += self.chunk
        if not self.speaking:
            self._recent.append(level)
            floor = min(min(self._recent), self.floor_cap)
            threshold = max(self.min_rms, floor * self.ratio)
            self._loud_run = self._loud_run + 1 if level > threshold else 0
            if self._loud_run >= 2:  # two chunks in a row: not a click
                self.speaking = True
                self._quiet_for = 0.0
                self._hold = threshold * 0.7
            elif self.elapsed >= self.start_timeout:
                return "no_speech"
        else:
            self._quiet_for = 0.0 if level > self._hold else self._quiet_for + self.chunk
            if self._quiet_for >= self.silence_seconds:
                return "done"
        if self.elapsed >= self.max_seconds:
            return "max" if self.speaking else "no_speech"
        return None


@dataclass(frozen=True)
class Recording:
    pcm: bytes
    reason: str  # done | max | stopped | no_speech

    @property
    def seconds(self) -> float:
        return len(self.pcm) / 2 / SAMPLE_RATE

    @property
    def usable(self) -> bool:
        return self.reason != "no_speech" and self.seconds >= MIN_SPEECH_SECONDS


class Recorder:
    async def record(
        self,
        stop: asyncio.Event,
        on_level: Callable[[float], None],
        *,
        start_timeout: Optional[float] = None,
        max_seconds: Optional[float] = None,
    ) -> Recording:
        """Record one utterance. The two limits default to the settings; a caller
        wanting a short listening window (e.g. for "stop" while an alarm rings)
        passes its own."""
        command = [
            "arecord", "-q", "-D", settings.mic_device, "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1", "-t", "raw",
        ]  # fmt: skip
        try:
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError as exc:
            raise MicUnavailable("Recording needs arecord, which isn't installed (alsa-utils)") from exc

        detector = EndpointDetector(
            silence_seconds=settings.voice_silence_seconds,
            start_timeout=settings.voice_start_timeout_seconds if start_timeout is None else start_timeout,
            max_seconds=settings.voice_max_seconds if max_seconds is None else max_seconds,
        )
        chunks: list[bytes] = []
        reason = "stopped"
        try:
            while not stop.is_set():
                try:
                    chunk = await asyncio.wait_for(process.stdout.readexactly(CHUNK_BYTES), timeout=2.0)
                except asyncio.IncompleteReadError as exc:
                    detail = (await process.stderr.read()).decode(errors="replace").strip()
                    raise MicUnavailable(detail or "The microphone stopped responding") from exc
                except asyncio.TimeoutError as exc:
                    raise MicUnavailable("The microphone isn't sending any audio") from exc
                chunks.append(chunk)
                level = rms(chunk)
                on_level(level)
                verdict = detector.feed(level)
                if verdict:
                    reason = verdict
                    break
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()
        return Recording(b"".join(chunks), reason)
