"""Saying "stop" or "snooze" while a timer or alarm is ringing — no wake word needed.

The kiosk has no echo cancellation, so it can't listen *through* its own chime.
Instead the two take turns (see timers/alerts.py): chime, a moment for the echo
to die away, then a short listening window here, then the next chime. If speech
is heard in the window it is recognized as usual, but matched against a very
small vocabulary: only a short, explicit "stop", "dismiss" or "snooze ..." acts;
anything else — including any other command, and ordinary conversation — is
ignored. (Those still work the normal way: "Hey Jarvis, ...".)
"""

import asyncio
import logging
from datetime import datetime
from typing import Callable, Optional

from sqlmodel import Session

from ..config import settings
from ..db import engine
from .core import Reply
from .mic import mic_lock
from .recorder import MicUnavailable
from .router import route_while_ringing
from .session import build_context, voice
from .tts import choose_speaker, clean_for_speech

logger = logging.getLogger(__name__)


def understand_while_ringing(text: str) -> Optional[Reply]:
    """Blocking; call it in a thread."""
    with Session(engine) as session:
        return route_while_ringing(text, build_context(session))


class RingListener:
    def __init__(
        self,
        *,
        recorder,
        transcriber,
        apply_fn: Callable[[str], Optional[Reply]] = understand_while_ringing,
        speaker_factory=choose_speaker,
        wake_getter: Callable[[], object] = lambda: None,
        history=None,
    ) -> None:
        self._recorder = recorder
        self._transcriber = transcriber
        self._apply = apply_fn
        self._speaker_factory = speaker_factory
        self._wake = wake_getter
        self._history = history
        self._warned = False

    def available(self) -> bool:
        return settings.voice_ring_listen and self._transcriber.status()[0]

    async def listen_once(self) -> bool:
        """One short listening window. True if a command was heard and acted on."""
        if not self.available() or mic_lock.locked():  # a conversation has the microphone
            return False
        try:
            async with mic_lock:
                wake = self._wake()
                if wake is not None:
                    await wake.pause()
                try:
                    recording = await self._recorder.record(
                        asyncio.Event(),
                        lambda _level: None,
                        start_timeout=settings.voice_ring_window_seconds,
                        max_seconds=settings.voice_ring_max_utterance_seconds,
                    )
                finally:
                    if wake is not None:
                        wake.resume()
        except MicUnavailable as exc:
            if not self._warned:
                logger.warning("Can't listen for 'stop' while ringing: %s", exc)
                self._warned = True
            return False
        self._warned = False
        if not recording.usable:
            return False

        try:
            text = await asyncio.to_thread(self._transcriber.transcribe, recording.pcm)
            if not text:
                return False
            reply = await asyncio.to_thread(self._apply, text)
        except Exception:
            logger.exception("Couldn't handle speech heard while ringing")
            return False

        self._remember(text, reply)
        if reply is None:
            return False  # something was said, but not a command for this: leave it alone
        speaker = self._speaker_factory()
        if speaker is not None:
            try:
                await speaker.speak(clean_for_speech(reply.text))
            except Exception:
                logger.exception("Couldn't speak the reply")
        return True

    def _remember(self, text: str, reply: Optional[Reply]) -> None:
        """Kept in the same short in-memory history as conversations, including
        what was heard and ignored — that's how false triggers get diagnosed."""
        if self._history is not None:
            self._history.append(
                {
                    "at": datetime.now().isoformat(timespec="seconds"),
                    "via": "ringing",
                    "transcript": text,
                    "reply": reply.text if reply else None,
                    "understood": reply is not None,
                    "ignored": reply is None,
                    "error": None,
                }
            )


ring_listener = RingListener(
    recorder=voice.recorder,
    transcriber=voice.transcriber,
    wake_getter=lambda: voice.wake,
    history=voice.history,
)
