"""Stepping out of the kiosk app to the desktop underneath, and back again.

Chromium in --kiosk mode draws no window frame or taskbar, and deploy/kiosk.sh
quits xfce4-panel too (see its own comment), so that a touch at a screen edge
can't pop the panel up over the app's header. That leaves nothing on screen to
click once the app's window is minimized, so minimizing brings the panel back,
and it is quit again as soon as the app's window is restored, whether from the
panel's taskbar or the desktop icon deploy/kiosk.sh installs (see
deploy/README.md "Minimizing to the desktop").
"""

import logging
import os
import subprocess
import threading
import time
from typing import Optional

from .config import settings

logger = logging.getLogger(__name__)


class SystemControlError(RuntimeError):
    pass


def _env() -> dict:
    env = {**os.environ, "DISPLAY": settings.browser_display}
    # The panel finds the desktop session's message bus (which it and its
    # settings live on) through this; a systemd service doesn't inherit it.
    if "DBUS_SESSION_BUS_ADDRESS" not in env and env.get("XDG_RUNTIME_DIR"):
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={env['XDG_RUNTIME_DIR']}/bus"
    return env


def _run(command: list[str]) -> str:
    """Runs a command; returns what it printed. Raises SystemControlError if it can't run or fails."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, env=_env())
    except FileNotFoundError as exc:
        raise SystemControlError(f"{command[0]} is not installed (see deploy/README.md)") from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemControlError(f"{command[0]} timed out") from exc
    if result.returncode != 0:
        raise SystemControlError(f"{' '.join(command)} failed: {result.stderr.strip()}")
    return result.stdout


def _panel_is_running() -> bool:
    result = subprocess.run(["pgrep", "-x", "xfce4-panel"], capture_output=True, timeout=5)
    return result.returncode == 0


def show_panel() -> None:
    """Brings the desktop panel (taskbar, menu) back. Only a convenience, so a
    failure is logged rather than stopping the minimize that asked for it."""
    try:
        if _panel_is_running():
            return
        # Detached, so it keeps running on its own and isn't waited for.
        subprocess.Popen(
            ["xfce4-panel"],
            env=_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError):
        logger.exception("Couldn't bring the desktop panel back")


def hide_panel() -> None:
    """Quits the panel again (same as deploy/kiosk.sh does at login). A failure
    just means it wasn't running."""
    try:
        subprocess.run(["xfce4-panel", "--quit"], capture_output=True, timeout=5, env=_env())
    except (OSError, subprocess.SubprocessError):
        logger.exception("Couldn't hide the desktop panel")


def _window_state(window: str) -> Optional[str]:
    """"Iconic" (minimized), "Normal", or None if the window doesn't exist (any more)."""
    try:
        output = _run(["xprop", "-id", window, "WM_STATE"])
    except SystemControlError:
        return None
    if "Iconic" in output:
        return "Iconic"
    return "Normal" if "Normal" in output else None


_PANEL_POLL_SECONDS = 1.0
# The window manager takes a moment to minimize; not seeing it minimized
# within this long means it isn't going to be.
_MINIMIZE_GRACE_SECONDS = 4.0
_watcher: Optional[threading.Thread] = None
_watcher_lock = threading.Lock()


def _hide_panel_once_restored(window: str) -> None:
    started = time.monotonic()
    was_minimized = False
    while True:
        time.sleep(_PANEL_POLL_SECONDS)
        state = _window_state(window)
        if state == "Iconic":
            was_minimized = True
        elif state is None or was_minimized or time.monotonic() - started > _MINIMIZE_GRACE_SECONDS:
            break
    hide_panel()


def _start_watching(window: str) -> None:
    global _watcher
    with _watcher_lock:
        if _watcher is not None and _watcher.is_alive():
            return  # already watching; it hides the panel when the window is back
        _watcher = threading.Thread(target=_hide_panel_once_restored, args=(window,), daemon=True)
        _watcher.start()


def minimize_to_desktop() -> None:
    """Minimizes whichever window is focused and brings the panel back. A
    request only ever reaches here from a click inside this app's own page, so
    that is always this app's own kiosk window, never the separate Browser-tab
    window, which doesn't have focus while this page does."""
    window = _run(["xdotool", "getactivewindow"]).strip()
    if not window:
        raise SystemControlError("no window has focus")
    _run(["xdotool", "windowminimize", window])
    show_panel()
    _start_watching(window)


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
