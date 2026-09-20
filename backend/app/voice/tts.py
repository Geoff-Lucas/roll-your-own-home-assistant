"""Speaking replies aloud.

Two engines behind one interface, chosen at runtime:
- Piper: a natural-sounding neural voice, fully local. Needs the piper-tts
  package and a voice file (a one-time download: `python -m app.voice.setup --piper NAME`).
- espeak-ng: robotic, but a plain distro package — the zero-setup fallback.
Both render to a WAV file and hand it to app.audio.player, so speech uses the
same speaker path (and the same configured device) as the timer chime.
"""

import asyncio
import os
import re
import shutil
import sys
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
            code = await _run(
                "espeak-ng", "-v", settings.voice_espeak_voice, "-s", str(settings.voice_espeak_speed),
                "-w", str(wav), "--", text,
            )  # fmt: skip
            if code != 0 or not wav.exists():
                raise SpeechError("espeak-ng couldn't render the reply")
            await play_and_wait(wav)


def piper_binary() -> Optional[Path]:
    """The piper executable: the configured one, else the one pip put beside our Python."""
    if settings.voice_piper_binary:
        path = Path(settings.voice_piper_binary)
        return path if path.exists() else None
    beside = Path(sys.executable).parent / ("piper.exe" if os.name == "nt" else "piper")
    if beside.exists():
        return beside
    found = shutil.which("piper")
    return Path(found) if found else None


def piper_model() -> Optional[Path]:
    """The chosen voice's .onnx file, or None if none is chosen or it isn't there."""
    name = settings.voice_piper_model
    if not name:
        return None
    is_path = name.endswith(".onnx") or "/" in name or "\\" in name
    path = Path(name) if is_path else settings.voice_piper_dir / f"{name}.onnx"
    return path if path.exists() else None


class PiperSpeaker:
    name = "piper"

    async def speak(self, text: str) -> None:
        binary, model = piper_binary(), piper_model()
        if binary is None or model is None:
            raise SpeechError("piper isn't installed, or its voice file is missing")
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "speech.wav"
            code = await _run(
                str(binary), "--model", str(model), "--output_file", str(wav),
                stdin=text.encode("utf-8"),
            )  # fmt: skip
            if code != 0 or not wav.exists():
                raise SpeechError("piper couldn't render the reply")
            await play_and_wait(wav)


def piper_available() -> bool:
    return piper_binary() is not None and piper_model() is not None


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
