"""The background clock that makes timers and alarms actually ring.

Runs server-side (not in the browser) on purpose: an alarm must sound even if
the page is showing something else, the browser tab is busy, or the Browser
tab's separate window is on top.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

from sqlmodel import Session

from ..audio.player import play_chime
from ..config import settings
from ..db import engine
from ..time_utils import to_naive_utc
from . import service

logger = logging.getLogger(__name__)

_TICK_SECONDS = 0.5


async def run_timer_loop() -> None:
    last_chime = float("-inf")
    while True:
        try:
            with Session(engine) as session:
                for timer in service.tick(session):
                    logger.info("%s %r is ringing", timer.kind, timer.label or timer.alarm_time or timer.id)
                audible = service.ringing_audibly(service.list_all(session), to_naive_utc(datetime.now(timezone.utc)))
            if audible and time.monotonic() - last_chime >= settings.timer_ring_repeat_seconds:
                # aplay runs in its own process, so this never blocks the loop.
                if play_chime():
                    last_chime = time.monotonic()
        except Exception:
            # A bad tick must never stop the clock — try again next time round.
            logger.exception("Timer tick failed")
        await asyncio.sleep(_TICK_SECONDS)
