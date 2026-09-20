"""Playing sounds through the speaker.

The one place that owns audio output, so timer chimes now — and spoken replies
from the voice assistant later — share a single, configurable path
(`settings.audio_device`, an ALSA name such as "default" or "plughw:0,7").
Playback is fire-and-forget via `aplay`; failures are logged, never raised, so
a missing or misconfigured speaker can't take a timer down with it.
"""

import logging
import math
import struct
import subprocess
import wave
from pathlib import Path
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)

_RATE = 48000
_current: Optional[subprocess.Popen] = None
_warned_missing = False
_warned_failed = False


def _tone(hz: float, start: float, length: float, total: int, amp: float) -> list[float]:
    """A bell-like note: a sine with an instant attack and exponential decay."""
    samples = [0.0] * total
    first = int(start * _RATE)
    for i in range(int(length * _RATE)):
        if first + i >= total:
            break
        t = i / _RATE
        samples[first + i] = amp * math.exp(-4.5 * t) * math.sin(2 * math.pi * hz * t)
    return samples


def write_chime(path: Path) -> None:
    """A short two-note chime (E6 then A6), generated rather than shipped as a
    binary so there is nothing to keep in the repo."""
    total = int(1.6 * _RATE)
    first = _tone(1318.5, 0.0, 1.0, total, 0.55)
    second = _tone(1760.0, 0.32, 1.2, total, 0.55)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(_RATE)
        frames = bytearray()
        for a, b in zip(first, second):
            value = max(-1.0, min(1.0, a + b))
            frames += struct.pack("<hh", int(value * 32767), int(value * 32767))
        out.writeframes(bytes(frames))


def chime_path() -> Path:
    path = settings.data_dir / "sounds" / "chime.wav"
    if not path.exists():
        write_chime(path)
    return path


def play_file(path: Path) -> bool:
    """Start playing `path`, unless the previous sound is still going (so a
    slow speaker never gets a pile of overlapping chimes). True if started."""
    global _current, _warned_missing, _warned_failed
    if _current is not None:
        status = _current.poll()
        if status is None:
            return False
        if status != 0 and not _warned_failed:
            # aplay starts fine and *then* fails (wrong device, device busy), so
            # the only place to notice is when reaping it on the next request.
            logger.warning(
                "aplay exited with status %s on audio device %r — check HOME_ORGANIZER_AUDIO_DEVICE",
                status,
                settings.audio_device,
            )
            _warned_failed = True
    try:
        _current = subprocess.Popen(
            ["aplay", "-q", "-D", settings.audio_device, str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except FileNotFoundError:
        if not _warned_missing:
            logger.warning("aplay not found — timers will ring on screen only (install alsa-utils)")
            _warned_missing = True
    except OSError:
        logger.exception("Couldn't start audio playback")
    _current = None
    return False


def play_chime() -> bool:
    return play_file(chime_path())
