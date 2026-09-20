"""Speaking replies aloud.

Two engines behind one interface, chosen at runtime:
- Piper: a natural-sounding neural voice, fully local. Needs the piper-tts
  package and a voice file (a one-time download: `python -m app.voice.setup --piper NAME`).
- espeak-ng: robotic, but a plain distro package — the zero-setup fallback.
Both render to a WAV file and hand it to app.audio.player, so speech uses the
same speaker path (and the same configured device) as the timer chime.
"""

import asyncio
import importlib.util
import logging
import re
import shutil
import tempfile
import threading
import wave
from pathlib import Path
from typing import Optional, Protocol

from ..audio.player import play_and_wait
from ..config import settings

logger = logging.getLogger(__name__)

MAX_SPOKEN_CHARS = 400


class SpeechError(RuntimeError):
    pass


class Speaker(Protocol):
    name: str

    async def speak(self, text: str) -> None: ...


def clean_for_speech(text: str) -> str:
    text = re.sub(r"[*_`#>|]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_SPOKEN_CHARS]


async def _run(*command: str, stdin: Optional[bytes] = None) -> int:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await process.communicate(stdin)
    return process.returncode


class EspeakSpeaker:
    name = "espeak-ng"

    async def speak(self, text: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "speech.wav"
            # "--" so a reply that begins with a dash is never read as an option.
            code = await _run(
                "espeak-ng", "-v", settings.voice_espeak_voice, "-s", str(settings.voice_espeak_speed),
                "-w", str(wav), "--", text,
            )  # fmt: skip
            if code != 0 or not wav.exists():
                raise SpeechError("espeak-ng couldn't render the reply")
            await play_and_wait(wav)


def piper_installed() -> bool:
    return importlib.util.find_spec("piper") is not None


def piper_model() -> Optional[Path]:
    """The chosen voice's .onnx file, or None if none is chosen or it isn't there."""
    name = settings.voice_piper_model
    if not name:
        return None
    is_path = name.endswith(".onnx") or "/" in name or "\\" in name
    path = Path(name) if is_path else settings.voice_piper_dir / f"{name}.onnx"
    return path if path.exists() else None


# Loading a voice takes over a second; rendering a sentence with it loaded takes
# a fraction of that. So the voice stays in memory (one at a time) instead of
# being loaded afresh for every reply.
_piper_lock = threading.RLock()
_piper_loaded: Optional[tuple] = None  # (model path, PiperVoice)


def _load_piper(model: Path):
    global _piper_loaded
    with _piper_lock:
        if _piper_loaded is None or _piper_loaded[0] != model:
            from piper import PiperVoice

            _piper_loaded = (model, PiperVoice.load(model))
        return _piper_loaded[1]


def _render_piper(model: Path, text: str, wav: Path) -> None:
    """Blocking; call it in a thread."""
    with _piper_lock:  # one render at a time: replies are spoken one after another anyway
        voice = _load_piper(model)
        with wave.open(str(wav), "wb") as out:
            voice.synthesize_wav(text, out)


async def warm_up() -> None:
    """Load the chosen Piper voice now, so the first reply isn't the slow one."""
    if settings.voice_tts not in ("auto", "piper") or not piper_installed():
        return
    model = piper_model()
    if model is None:
        return
    try:
        await asyncio.to_thread(_load_piper, model)
        logger.info("Reply voice %s loaded", model.stem)
    except Exception:
        logger.exception("Couldn't load the Piper voice; replies will load it on demand")


class PiperSpeaker:
    name = "piper"

    async def speak(self, text: str) -> None:
        model = piper_model()
        if not piper_installed() or model is None:
            raise SpeechError("piper isn't installed, or its voice file is missing")
        if not text.strip():
            return
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "speech.wav"
            try:
                await asyncio.to_thread(_render_piper, model, text, wav)
            except Exception as exc:
                raise SpeechError(f"piper couldn't render the reply: {exc}") from exc
            await play_and_wait(wav)


def piper_available() -> bool:
    return piper_installed() and piper_model() is not None


def choose_speaker() -> Optional[Speaker]:
    """The best available voice, or None (replies then show on screen only)."""
    mode = settings.voice_tts
    if mode == "none":
        return None
    if mode in ("auto", "piper") and piper_available():
        return PiperSpeaker()
    if mode in ("auto", "espeak") and shutil.which("espeak-ng"):
        return EspeakSpeaker()
    return None
