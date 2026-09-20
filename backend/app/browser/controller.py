"""Owns the second Chromium process and everything done to it.

See window.py for the window-manager side and cdp.py for the DevTools side.
The process is launched lazily the first time the Browser tab is opened and
then kept (hidden, not closed) so the page you were on is still there when you
come back. It lives in the backend service's process group, so a redeploy or
restart closes it.
"""

import asyncio
import logging
import os
import shutil
import subprocess
from typing import Optional

from ..config import settings
from . import cdp, window
from .urls import normalize_address

logger = logging.getLogger(__name__)


class BrowserUnavailable(RuntimeError):
    """The browser can't be run here (no display/tools) or failed to start."""


class BrowserController:
    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None
        self._window: Optional[str] = None
        self._lock = asyncio.Lock()

    def _alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    async def _ready(self) -> bool:
        return self._alive() and self._window is not None and await asyncio.to_thread(window.exists, self._window)

    async def ensure_running(self) -> None:
        async with self._lock:
            if await self._ready():
                return
            await self._launch()

    async def _launch(self) -> None:
        for tool in (settings.browser_command, "xdotool", "wmctrl"):
            if shutil.which(tool) is None:
                raise BrowserUnavailable(f"Browser control needs {tool}, which isn't installed on this machine")

        self._terminate()
        settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        command = [
            settings.browser_command,
            "--kiosk",
            f"--user-data-dir={settings.browser_profile_dir}",
            f"--remote-debugging-port={settings.browser_debug_port}",
            "--remote-debugging-address=127.0.0.1",  # never expose DevTools beyond this machine
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--noerrdialogs",
            "--disable-notifications",  # sites asking to "show notifications" are pure noise on a kiosk
            "--password-store=basic",  # never touch the (locked-on-autologin) system keyring
            settings.browser_home_url,
        ]
        env = {**os.environ, "DISPLAY": settings.browser_display}
        logger.info("Starting browser window")
        self._process = subprocess.Popen(
            command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
        self._window = await asyncio.to_thread(window.wait_for_window, self._process.pid)
        if self._window is None:
            self._terminate()
            raise BrowserUnavailable("The browser window didn't appear")

    def _terminate(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
        self._process = None
        self._window = None

    async def shutdown(self) -> None:
        self._terminate()

    async def show(self, x: int, y: int, width: int, height: int) -> None:
        await self.ensure_running()
        try:
            await asyncio.to_thread(window.place, self._window, x, y, width, height)
        except window.WindowError as exc:
            raise BrowserUnavailable(str(exc)) from exc

    async def hide(self) -> None:
        if not await self._ready():
            return  # nothing running, nothing to hide
        try:
            await asyncio.to_thread(window.hide, self._window)
        except window.WindowError as exc:
            logger.warning("Couldn't hide the browser window: %s", exc)

    async def navigate(self, address: str) -> None:
        url = normalize_address(address)  # ValueError -> 400 in the router
        await self.ensure_running()
        await cdp.navigate(url)

    async def back(self) -> None:
        await self.ensure_running()
        await cdp.step_history(-1)

    async def forward(self) -> None:
        await self.ensure_running()
        await cdp.step_history(+1)

    async def reload(self) -> None:
        await self.ensure_running()
        await cdp.reload()

    async def current_url(self) -> Optional[str]:
        if not await self._ready():
            return None
        return (await cdp.first_page()).get("url")

    async def state(self) -> dict:
        if not await self._ready():
            return {"running": False, "url": None, "title": None, "can_go_back": False, "can_go_forward": False}
        page = await cdp.first_page()
        history = await cdp.send(page, "Page.getNavigationHistory")
        return {
            "running": True,
            "url": page.get("url"),
            "title": page.get("title"),
            "can_go_back": history["currentIndex"] > 0,
            "can_go_forward": history["currentIndex"] < len(history["entries"]) - 1,
        }


controller = BrowserController()
