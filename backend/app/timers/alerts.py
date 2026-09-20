"""The background clock that makes timers and alarms actually ring.

Runs server-side (not in the browser) on purpose: an alarm must sound even if
the page is showing something else, the browser tab is busy, or the Browser
tab's separate window is on top.

While something rings, the chime and a short listening window for "stop" or
"snooze" take turns (see voice/ringing.py for why they can't overlap).
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from sqlmodel import Session

from ..audio.player import chime_path, play_and_wait
from ..config import settings
from ..db import engine
from ..time_utils import to_naive_utc
from . import service

logger = logging.getLogger(__name__)

_TICK_SECONDS = 0.5
_REVERB_SECONDS = 0.35  # let the chime's tail die away before listening


def _ringing_audibly() -> bool:
    with Session(engine) as session:
        return service.ringing_audibly(service.list_all(session), to_naive_utc(datetime.now(timezone.utc)))


async def _play_chime() -> None:
    await play_and_wait(chime_path())


async def ring_once(
    *,
    play: Callable[[], Awaitable[None]],
    listen: Optional[Callable[[], Awaitable[bool]]],
    is_ringing: Callable[[], bool],
    repeat_seconds: float,
    reverb_seconds: float = _REVERB_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """One cycle of ringing: the chime, then either a listening window (when
    voice dismissal is available) or a plain pause to keep the old cadence.
    Stops early the moment nothing is ringing any more (dismissed on screen, or by voice)."""
    started = clock()
    await play()
    if not is_ringing():
        return
    if listen is None:
        await sleep(max(0.0, repeat_seconds - (clock() - started)))
        return
    await sleep(reverb_seconds)
    if is_ringing():
        await listen()


async def run_timer_loop() -> None:
    # Imported here, not at module level: the voice package imports the timers
    # package, so importing it at the top would be circular.
    from ..voice.ringing import ring_listener
    from ..voice.session import voice

    while True:
        try:
            with Session(engine) as session:
                for timer in service.tick(session):
                    logger.info("%s %r is ringing", timer.kind, timer.label or timer.alarm_time or timer.id)
            if _ringing_audibly() and not voice.busy:  # not while someone is mid-conversation
                await ring_once(
                    play=_play_chime,
                    listen=ring_listener.listen_once if ring_listener.available() else None,
                    is_ringing=_ringing_audibly,
                    repeat_seconds=settings.timer_ring_repeat_seconds,
                )
                continue
        except Exception:
            # A bad tick must never stop the clock — try again next time round.
            logger.exception("Timer tick failed")
        await asyncio.sleep(_TICK_SECONDS)
