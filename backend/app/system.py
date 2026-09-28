"""Stepping out of the kiosk app to the desktop underneath, and back again.

Chromium in --kiosk mode draws no window frame or taskbar, and deploy/kiosk.sh
quits xfce4-panel too (see its own comment) — so once the app's window is
minimized there is nothing on screen left to click to bring it back.
deploy/kiosk.sh installs a desktop icon that does that (see deploy/README.md
"Minimizing to the desktop").
"""

import os
import subprocess

from .config import settings


class SystemControlError(RuntimeError):
    pass


def _run(command: list[str]) -> None:
    env = {**os.environ, "DISPLAY": settings.browser_display}
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, env=env)
    except FileNotFoundError as exc:
        raise SystemControlError(f"{command[0]} is not installed (see deploy/README.md)") from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemControlError(f"{command[0]} timed out") from exc
    if result.returncode != 0:
        raise SystemControlError(f"{' '.join(command)} failed: {result.stderr.strip()}")


def minimize_to_desktop() -> None:
    """Minimizes whichever window is focused. A request only ever reaches
    here from a click inside this app's own page, so that is always this
    app's own kiosk window — never the separate Browser-tab window, which
    doesn't have focus while this page does."""
    _run(["xdotool", "getactivewindow", "windowminimize"])


# Restarting the computer, for "Hey Jarvis, restart the kiosk" (voice/skills/
# system.py): it fixed a touchscreen that stopped responding in part of the
# screen, and voice still works when touch doesn't. The app runs as a normal
# user, so this needs sudo allowed without a password for `systemctl reboot`
# (see deploy/README.md); `sudo -n` fails at once rather than waiting for one.
_REBOOT = ["sudo", "-n", "systemctl", "reboot"]


def can_reboot() -> bool:
    """Whether this machine lets the app reboot it (asks sudo; changes nothing)."""
    try:
        result = subprocess.run(["sudo", "-n", "-l", "systemctl", "reboot"], capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def reboot() -> None:
    _run(_REBOOT)
