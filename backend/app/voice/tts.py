"""Speaking replies aloud.

Two engines behind one interface, chosen at runtime:
- Piper: a natural-sounding neural voice, fully local. Needs its executable and
  a voice file (see settings), which are a separate one-time download.
- espeak-ng: robotic, but a plain distro package — the zero-setup fallback.
Both render to a WAV file and hand it to app.audio.player, so speech uses the
same speaker path (and the same configured device) as the timer chime.
"""

import asyncio
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Protocol

from ..audio.player import play_and_wait
from ..config import settings

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
            code = await _run("espeak-ng", "-v", "en-us", "-s", "160", "-w", str(wav), "--", text)
            if code != 0 or not wav.exists():
                raise SpeechError("espeak-ng couldn't render the reply")
            await play_and_wait(wav)


class PiperSpeaker:
    name = "piper"

    async def speak(self, text: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "speech.wav"
            code = await _run(
                settings.voice_piper_binary,
                "--model",
                settings.voice_piper_model,
                "--output_file",
                str(wav),
                stdin=text.encode("utf-8"),
            )
            if code != 0 or not wav.exists():
                raise SpeechError("piper couldn't render the reply")
            await play_and_wait(wav)


def piper_available() -> bool:
    return bool(
        settings.voice_piper_binary
        and settings.voice_piper_model
        and Path(settings.voice_piper_binary).exists()
        and Path(settings.voice_piper_model).exists()
    )


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
