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
