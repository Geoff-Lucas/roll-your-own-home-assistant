"""X11 window control for the browser window, via xdotool and wmctrl.

Why this is shaped the way it is (all verified on the kiosk, XFCE/xfwm4):
- The browser is launched with --kiosk because kiosk-mode Chromium draws no
  window frame; taking it out of fullscreen afterwards leaves a frameless
  window that can be sized exactly. (--app windows get a title bar that can't
  be removed.)
- "Always on top" is what keeps it above the app's own window when the app
  takes focus. A focused *fullscreen* window covers everything, including
  always-on-top windows, so the app window is also taken out of fullscreen
  (see deploy/kiosk.sh).
"""

import os
import subprocess
import time
from typing import Optional

from ..config import settings

_STEP_PAUSE = 0.15  # the window manager handles requests asynchronously


class WindowError(RuntimeError):
    pass


def _run(command: list[str]) -> str:
    env = {**os.environ, "DISPLAY": settings.browser_display}
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, env=env)
    except FileNotFoundError as exc:
        raise WindowError(f"{command[0]} is not installed (see deploy/README.md)") from exc
    except subprocess.TimeoutExpired as exc:
        raise WindowError(f"{command[0]} timed out") from exc
    if result.returncode != 0:
        raise WindowError(f"{' '.join(command)} failed: {result.stderr.strip()}")
    return result.stdout


def find_window(pid: int) -> Optional[str]:
    """The (largest) window owned by a process, or None if it has none yet."""
    try:
        ids = _run(["xdotool", "search", "--pid", str(pid), "--onlyvisible"]).split()
    except WindowError:
        return None  # xdotool exits non-zero when nothing matches
    return ids[-1] if ids else None


def wait_for_window(pid: int, timeout: float = 15.0) -> Optional[str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = find_window(pid)
        if found:
            return found
        time.sleep(0.25)
    return None


def exists(window_id: str) -> bool:
    try:
        _run(["xdotool", "getwindowname", window_id])
        return True
    except WindowError:
        return False


def place(window_id: str, x: int, y: int, width: int, height: int) -> None:
    """Show the window frameless at an exact screen rectangle, above the app."""
    _run(["xdotool", "windowmap", window_id])
    time.sleep(_STEP_PAUSE)
    _run(["wmctrl", "-i", "-r", window_id, "-b", "remove,fullscreen"])
    time.sleep(_STEP_PAUSE)
    _run(["wmctrl", "-i", "-r", window_id, "-e", f"0,{x},{y},{width},{height}"])
    _run(["wmctrl", "-i", "-r", window_id, "-b", "add,above"])


def hide(window_id: str) -> None:
    _run(["xdotool", "windowunmap", window_id])
