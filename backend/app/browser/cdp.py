"""Minimal Chrome DevTools Protocol client for steering the browser window.

The debugging port is bound to 127.0.0.1 only (see controller.py) — CDP gives
total control of the browser, so it must never be reachable from the network.
Each command opens a short-lived connection to the page's own websocket; that's
plenty fast for tap-driven use and keeps this free of connection state.
"""

import asyncio
import json
from typing import Any, Optional

import httpx
import websockets

from ..config import settings

_TIMEOUT = 5


class CDPError(RuntimeError):
    pass


def _base_url() -> str:
    return f"http://127.0.0.1:{settings.browser_debug_port}"


async def list_pages() -> list[dict]:
    """Open tabs, most recently active first. In kiosk mode only the active
    tab is visible, so the first one is "the page you're looking at"."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(f"{_base_url()}/json/list")
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise CDPError(f"Browser isn't reachable: {exc}") from exc
    return [target for target in response.json() if target.get("type") == "page"]


async def first_page() -> dict:
    pages = await list_pages()
    if not pages:
        raise CDPError("The browser has no open page")
    return pages[0]


async def send(page: dict, method: str, params: Optional[dict] = None) -> Any:
    async def _exchange() -> Any:
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            await ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
            async for raw in ws:
                message = json.loads(raw)
                if message.get("id") != 1:
                    continue  # an event, not our reply
                if "error" in message:
                    raise CDPError(message["error"].get("message", "DevTools command failed"))
                return message.get("result", {})
        raise CDPError("The browser closed the connection")

    try:
        return await asyncio.wait_for(_exchange(), timeout=_TIMEOUT)
    except (asyncio.TimeoutError, OSError, websockets.WebSocketException) as exc:
        raise CDPError(f"Browser command {method} failed: {exc}") from exc


async def navigate(url: str) -> None:
    await send(await first_page(), "Page.navigate", {"url": url})


async def reload() -> None:
    await send(await first_page(), "Page.reload")


async def navigation_history() -> dict:
    return await send(await first_page(), "Page.getNavigationHistory")


async def step_history(delta: int) -> bool:
    """Go back (-1) or forward (+1) one entry. False if there's nowhere to go."""
    page = await first_page()
    history = await send(page, "Page.getNavigationHistory")
    target = history["currentIndex"] + delta
    if not 0 <= target < len(history["entries"]):
        return False
    await send(page, "Page.navigateToHistoryEntry", {"entryId": history["entries"][target]["id"]})
    return True
