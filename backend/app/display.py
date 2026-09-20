"""Waking the kiosk's screen from its idle sleep.

After ten minutes without a touch, X blanks the screen and drops the HDMI
signal, so the monitor sleeps — and its speakers, which are fed over that same
cable, go silent with it. The app can still hear ("Hey Jarvis") and still has
timers to ring, but nobody can see or hear it. `wake_display()` undoes that.

Sleep shows up in PulseAudio too: the HDMI speaker output vanishes and the
default output becomes a null sink that swallows sound. That is how this tells
a sleeping screen from an awake one, so it knows whether to wait for the monitor.
"""

import asyncio
import logging
import os
from typing import Awaitable, Callable

from .config import settings

logger = logging.getLogger(__name__)

_warned = False


async def _run(*command: str) -> tuple[int, str]:
    env = {**os.environ, "DISPLAY": settings.browser_display}
    process = await asyncio.create_subprocess_exec(
        *command,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(process.communicate(), timeout=3)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return 1, ""
    return process.returncode, out.decode(errors="replace").strip()


async def speakers_asleep() -> bool:
    """True when the default audio output is PulseAudio's null sink (screen asleep)."""
    try:
        code, sink = await _run("pactl", "get-default-sink")
    except FileNotFoundError:
        return False
    return code == 0 and "null" in sink


async def wake_display(sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> bool:
    """Wake the screen if it is asleep, and give the monitor a moment to come back.

    Safe to call whenever: on an awake screen it does nothing visible and returns
    at once. Returns whether the screen had been asleep.
    """
    global _warned
    try:
        was_asleep = await speakers_asleep()
        await _run("xset", "s", "reset")  # ends the screen-saver blank
        await _run("xset", "dpms", "force", "on")  # and DPMS off, if that is what is in use
    except FileNotFoundError:
        if not _warned:
            _warned = True
            logger.info("xset isn't installed, so the screen can't be woken from the app")
        return False
    except Exception:
        # Waking the screen is a courtesy; it must never get in the way of what needs the screen.
        logger.exception("Couldn't wake the screen")
        return False
    if was_asleep:
        logger.info("Woke the screen")
        await sleep(settings.display_wake_settle_seconds)
    return was_asleep
