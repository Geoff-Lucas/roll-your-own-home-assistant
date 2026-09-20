"""One voice interaction, start to finish: listen → transcribe → understand → speak.

A single shared session (there is one microphone and one speaker), driven by
the frontend over a few small endpoints (see routers/voice.py). The frontend
starts it and polls `snapshot()`; everything else happens here, server-side,
because the microphone and speaker belong to the machine, not the browser.
"""

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from sqlmodel import Session

from ..audio.player import ack_path, play_and_wait
from ..db import engine
from ..display import wake_display
from ..locations import get_current_location
from ..time_utils import to_naive_utc
from ..timers import service
from ..weather import get_cached_weather
from .core import Context, Reply
from .mic import mic_lock
from .recorder import MicUnavailable, Recorder
from .router import route
from .stt import SpeechRecognitionUnavailable, WhisperTranscriber
from .tts import Speaker, choose_speaker, clean_for_speech

logger = logging.getLogger(__name__)

BUSY_STATES = ("listening", "transcribing", "thinking", "speaking")
LEVEL_FULL_SCALE = 3000.0  # rms that fills the on-screen level meter


class VoiceBusy(RuntimeError):
    pass


def build_context(session: Session) -> Context:
    location = get_current_location(session)
    return Context(
        session=session,
        now=to_naive_utc(datetime.now(timezone.utc)),
        tz=service.local_tz(),
        weather=get_cached_weather(),
        location_name=location.name if location else None,
    )


def understand(text: str) -> Reply:
    """Run a command against the live database. Blocking; call it in a thread."""
    with Session(engine) as session:
        return route(text, build_context(session))


async def play_ack() -> None:
    """The short "I'm listening" tone after the wake word."""
    await play_and_wait(ack_path())


class VoiceSession:
    def __init__(
        self,
        *,
        recorder=None,
        transcriber=None,
        speaker_factory: Callable[[], Optional[Speaker]] = choose_speaker,
        understand_fn: Callable[[str], Reply] = understand,
        ack_fn: Callable[[], Awaitable[None]] = play_ack,
        wake_screen_fn: Callable[[], Awaitable[object]] = wake_display,
    ) -> None:
        self.recorder = recorder or Recorder()
        self.transcriber = transcriber or WhisperTranscriber()
        self._speaker_factory = speaker_factory
        self._understand = understand_fn
        self._ack = ack_fn
        self._wake_screen = wake_screen_fn
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        # The always-on wake-word listener, if one is running. The microphone can
        # only be opened by one thing at a time, so it is paused while a
        # conversation uses it and resumed shortly after the reply has been
        # spoken (the delay keeps it from hearing the tail of the reply).
        self.wake = None
        self.resume_delay = 0.6
        # The last few interactions, in memory only (gone on restart): what was
        # heard vs. answered, and how long each stage took — for tuning against
        # real use ("it heard X when I said Y"), never persisted.
        self.history: deque[dict] = deque(maxlen=25)
        self._reset()

    def _reset(self) -> None:
        self.timing: dict[str, float] = {}
        self.state = "idle"  # idle | listening | transcribing | thinking | speaking | done
        self.transcript: Optional[str] = None
        self.reply: Optional[str] = None
        self.understood: Optional[bool] = None
        self.error: Optional[str] = None
        self.level = 0.0
        self.finished_at: Optional[float] = None

    @property
    def busy(self) -> bool:
        return self.state in BUSY_STATES

    def snapshot(self) -> dict:
        return {
            "state": self.state,
            "transcript": self.transcript,
            "reply": self.reply,
            "understood": self.understood,
            "error": self.error,
            "level": round(self.level, 3),
        }

    def _finish(self, error: Optional[str] = None) -> None:
        self.error = error
        self.level = 0.0
        self.state = "done"
        self.finished_at = time.time()
        self.history.append(
            {
                "at": datetime.now().isoformat(timespec="seconds"),
                "transcript": self.transcript,
                "reply": self.reply,
                "understood": self.understood,
                "error": error,
                **self.timing,
            }
        )
        self._resume_wake()

    def _on_level(self, rms_level: float) -> None:
        self.level = min(1.0, rms_level / LEVEL_FULL_SCALE)

    # --- listening by microphone --------------------------------------------

    def attach_wake(self, listener) -> None:
        self.wake = listener

    def wake_status(self) -> dict:
        if self.wake is None:
            return {"enabled": False, "listening": False, "phrase": None}
        return {
            "enabled": True,
            "listening": self.wake.listening,
            "phrase": self.wake.phrase,
            "threshold": self.wake.threshold,
            "recent_peak_score": round(self.wake.recent_peak_score, 3),
            "recent_peak_level": round(self.wake.recent_peak_level),
        }

    def _resume_wake(self) -> None:
        if self.wake is None:
            return
        try:
            asyncio.get_running_loop().call_later(self.resume_delay, self.wake.resume)
        except RuntimeError:  # no running loop (e.g. finishing during shutdown)
            self.wake.resume()

    async def start(self, ack: bool = False) -> None:
        """Begin listening. `ack` plays the short tone first — used after the
        wake word, so the person knows to speak now (and the microphone isn't
        open while the tone plays, or it would hear the tone)."""
        if self.busy:
            raise VoiceBusy("Already listening")
        self._reset()
        self._stop.clear()
        self.state = "listening"
        self._task = asyncio.create_task(self._listen(ack))

    def stop(self) -> None:
        """End the recording now (whatever was heard so far is still processed)."""
        self._stop.set()

    async def _listen(self, ack: bool = False) -> None:
        try:
            async with mic_lock:  # held from taking the microphone to done recording
                if self.wake is not None:
                    await self.wake.pause()  # release the microphone
                ready, why = self.transcriber.status()
                if not ready:
                    self._finish(error=why)
                    return
                if ack:
                    # Heard from across the room, so the screen may well be asleep — and
                    # the tone would be lost, and the panel unseen, until it is awake.
                    await self._wake_screen()
                    await self._ack()
                recording = await self.recorder.record(self._stop, self._on_level)
            if not recording.usable:
                self._finish(error="I didn't hear anything.")
                return
            self.state = "transcribing"
            self.level = 0.0
            self.timing["recorded_seconds"] = round(recording.seconds, 2)
            started = time.monotonic()
            text = await asyncio.to_thread(self.transcriber.transcribe, recording.pcm)
            self.timing["recognized_in_seconds"] = round(time.monotonic() - started, 2)
            if not text:
                self._finish(error="I couldn't make that out.")
                return
            self.transcript = text
            await self._respond(text)
        except (MicUnavailable, SpeechRecognitionUnavailable) as exc:
            logger.warning("Voice input unavailable: %s", exc)
            self._finish(error=str(exc))
        except Exception:
            logger.exception("Voice interaction failed")
            self._finish(error="Something went wrong.")

    # --- understanding and answering ----------------------------------------

    async def _respond(self, text: str, speak: bool = True) -> Reply:
        self.state = "thinking"
        reply = await asyncio.to_thread(self._understand, text)
        self.reply = reply.text
        self.understood = reply.understood
        if speak:
            speaker = self._speaker_factory()
            if speaker is not None:
                self.state = "speaking"
                try:
                    await speaker.speak(clean_for_speech(reply.text))
                except Exception:
                    # The answer is already on screen; a broken voice shouldn't lose it.
                    logger.exception("Couldn't speak the reply")
        self._finish()
        return reply

    async def say_text(self, text: str, speak: bool = True) -> Reply:
        """The same path as a spoken command, minus the microphone — for typed
        commands and for testing everything after speech recognition."""
        if self.busy:
            raise VoiceBusy("Already busy")
        self._reset()
        self.transcript = text
        return await self._respond(text, speak=speak)


voice = VoiceSession()
