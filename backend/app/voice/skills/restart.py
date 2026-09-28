"""Restarting the kiosk by voice: "Hey Jarvis, restart the kiosk".

A restart fixed a touchscreen that stopped responding in part of the screen,
and when touch is the thing that's broken, voice still works. It always takes
two steps, so a misheard phrase or the TV can't reboot the machine: the first
asks for confirmation, and "restart now" within the window carries it out. The
reply says so before the screen goes dark (the reboot runs after it's spoken:
Reply.then, see session.run_action).
"""

import re
from datetime import datetime, timedelta
from typing import Optional

from ... import system as host
from ...config import settings
from ..core import Context, Reply

_VERB = re.compile(r"\b(restart|reboot)\b")
_TARGET = re.compile(r"\b(kiosk|computer|system|machine|device|screen|yourself|home organizer)\b")
_CONFIRM = re.compile(r"(yes |ok |okay )?(please )?(restart|reboot)( it)? now( please)?")
# "Restart the timer" and friends belong to the timer commands, not here.
_NOT_THE_COMPUTER = re.compile(r"\b(timer|timers|alarm|alarms|stopwatch|song|music|video)\b")

# When a restart was asked for and until when "restart now" confirms it (naive
# UTC, like Context.now). One kiosk, one pending request at a time.
_pending_until: Optional[datetime] = None


def _asked(t: str) -> bool:
    if not _VERB.search(t) or _NOT_THE_COMPUTER.search(t):
        return False
    return bool(_TARGET.search(t)) or t in ("restart", "reboot")


def handle(t: str, ctx: Context) -> Optional[Reply]:
    global _pending_until
    confirming = bool(_CONFIRM.fullmatch(t))
    if not (confirming or _asked(t)):
        return None
    if not settings.voice_restart_enabled:
        return Reply("Restarting by voice is turned off.", understood=False)

    if confirming and _pending_until is not None and ctx.now <= _pending_until:
        _pending_until = None
        return Reply("Restarting now. I'll be back in about a minute.", then="reboot")

    if not host.can_reboot():
        return Reply("I'm not allowed to restart this computer. The setup notes say how to allow it.", understood=False)
    seconds = settings.voice_restart_confirm_seconds
    _pending_until = ctx.now + timedelta(seconds=seconds)
    return Reply(f"To restart the kiosk, say restart now within {seconds} seconds.")
