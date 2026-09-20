"""Local speech-to-text with faster-whisper.

Runs entirely on this machine: what is said never leaves the house (only, later,
the *text* of a question that needs the Claude API). The model is a one-time
download and is never fetched behind your back — unless
HOME_ORGANIZER_VOICE_STT_AUTO_DOWNLOAD is set, a missing model is reported as
"not installed", and `python -m app.voice.setup` is how it gets installed.
"""

import logging
import threading
from pathlib import Path
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)

# Nudges the model toward the vocabulary of the commands it will actually hear
# ("timer", "alarm", "stopwatch"), which matters most for short utterances.
PROMPT = (
    "Set a timer for ten minutes. Set an alarm for seven a.m. Cancel the timer. Start the stopwatch. "
    "What time is it? What's the weather tomorrow? Will it rain today?"
)


class SpeechRecognitionUnavailable(RuntimeError):
    """Speech recognition isn't installed or set up on this machine."""


def installed_model_files(name: str) -> list[Path]:
    """Where faster-whisper keeps a model once downloaded (Hugging Face cache layout)."""
    return list(settings.voice_models_dir.glob(f"models--Systran--faster-whisper-{name}/snapshots/*/model.bin"))


class WhisperTranscriber:
    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()

    def status(self) -> tuple[bool, str]:
        """(ready, explanation). Checks without loading anything or touching the network."""
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False, "Speech recognition isn't installed (the faster-whisper package is missing)."
        if not settings.voice_stt_auto_download and not installed_model_files(settings.voice_stt_model):
            return False, (
                f"The speech model '{settings.voice_stt_model}' isn't installed yet. "
                "Run: python -m app.voice.setup"
            )
        return True, "ready"

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                ready, why = self.status()
                if not ready:
                    raise SpeechRecognitionUnavailable(why)
                logger.info("Loading speech model %s", settings.voice_stt_model)
                self._model = WhisperModel(
                    settings.voice_stt_model,
                    device="cpu",
                    compute_type="int8",
                    download_root=str(settings.voice_models_dir),
                    local_files_only=not settings.voice_stt_auto_download,
                )
            return self._model

    def transcribe(self, pcm: bytes) -> str:
        """16 kHz mono 16-bit PCM in, text out. Blocking — run it in a thread."""
        import numpy as np

        model = self._load()
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = model.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=True,  # trims silence and ignores non-speech noise
            initial_prompt=PROMPT,
            condition_on_previous_text=False,
            temperature=0.0,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
