from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlmodel import Session, select

from ..models import Event
from ..time_utils import to_naive_utc

_Key = Tuple[str, Optional[str]]  # (uid, recurrence_id)


def _in_window(row: Event, window_start: datetime, window_end: datetime) -> bool:
    # row.start_time/end_time are always naive-UTC (Event's validator); the
    # window bounds passed in may be tz-aware (worker.py uses
    # datetime.now(timezone.utc) arithmetic), so normalize before comparing.
    window_start = to_naive_utc(window_start)
    window_end = to_naive_utc(window_end)
    if row.all_day:
        return row.end_date >= window_start.date() and row.start_date <= window_end.date()
    return row.end_time >= window_start and row.start_time <= window_end


def reconcile_account_events(
    session: Session,
    account_id: int,
    parsed_events: List[Event],
    window_start: datetime,
    window_end: datetime,
) -> None:
    """Reconcile freshly-fetched-and-parsed events for one account against
    the local cache, scoped to [window_start, window_end].

    Upserts everything present in `parsed_events` (keyed by uid +
    recurrence_id). Deletes cached rows that fall inside the window but
    weren't seen this cycle (removed on the server) — deletion is
    deliberately scoped to the window, since the CalDAV fetch itself was
    windowed: a cached row outside the fetch range simply wasn't asked
    about, and dropping it would silently destroy data we have no evidence
    was actually removed upstream.
    """
    existing = session.exec(select(Event).where(Event.account_id == account_id)).all()
    existing_by_key: Dict[_Key, Event] = {(e.uid, e.recurrence_id): e for e in existing}

    seen: set[_Key] = set()
    for parsed in parsed_events:
        key = (parsed.uid, parsed.recurrence_id)
        seen.add(key)
        current = existing_by_key.get(key)
        if current is None:
            session.add(parsed)
        else:
            for field in (
                "title",
                "description",
                "location",
                "start_time",
                "end_time",
                "timezone",
                "all_day",
                "start_date",
                "end_date",
                "rrule",
            ):
                setattr(current, field, getattr(parsed, field))
            session.add(current)

    for key, row in existing_by_key.items():
        if key in seen:
            continue
        if _in_window(row, window_start, window_end):
            session.delete(row)

    session.commit()
