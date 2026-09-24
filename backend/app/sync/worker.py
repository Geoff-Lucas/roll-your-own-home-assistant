import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from ..config import settings
from ..db import engine
from ..models import Account
from .caldav_client import fetch_account_ics
from .ics_parser import parse_ics_resource
from .locks import account_lock
from .reconciler import reconcile_account_events

logger = logging.getLogger(__name__)


def sync_once() -> None:
    """Sync every linked account once.

    Tolerant of per-account failure by design: an unreachable server or a
    revoked app-specific password gets logged and skipped, and never blocks
    other accounts or crashes the worker loop — see PLAN.md "Offline
    behavior".
    """
    window_start = datetime.now(timezone.utc) - timedelta(days=settings.sync_window_past_days)
    window_end = datetime.now(timezone.utc) + timedelta(days=settings.sync_window_future_days)

    with Session(engine) as session:
        accounts = session.exec(select(Account)).all()
        for account in accounts:
            try:
                # Held from fetch through reconcile, so a local write can't land
                # in between and be judged against a stale fetch (see locks.py).
                with account_lock(account.id):
                    raw_resources = fetch_account_ics(account, window_start, window_end)
                    parsed = []
                    for raw in raw_resources:
                        parsed.extend(parse_ics_resource(raw, account.id, window_start, window_end))
                    reconcile_account_events(session, account.id, parsed, window_start, window_end)
            except Exception:
                logger.exception(
                    "CalDAV sync failed for account %s (%s) — will retry next cycle",
                    account.id,
                    account.display_name,
                )


async def run_sync_loop() -> None:
    while True:
        await asyncio.to_thread(sync_once)
        await asyncio.sleep(settings.sync_interval_seconds)
