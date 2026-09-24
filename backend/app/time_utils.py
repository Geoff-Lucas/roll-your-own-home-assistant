from datetime import date, datetime, timezone, tzinfo
from zoneinfo import ZoneInfo

import tzlocal

from .config import settings


def local_tz() -> tzinfo:
    """The household's timezone: HOME_ORGANIZER_TIMEZONE, else the machine's own."""
    if settings.timezone:
        return ZoneInfo(settings.timezone)
    return tzlocal.get_localzone()


def local_date(naive_utc: datetime) -> date:
    """The household's calendar day for a stored naive-UTC instant. Not just
    .date(): 8 PM Eastern is already tomorrow in UTC."""
    return naive_utc.replace(tzinfo=timezone.utc).astimezone(local_tz()).date()


def local_today() -> date:
    return datetime.now(local_tz()).date()


def to_naive_utc(value: datetime) -> datetime:
    """Normalize a datetime to naive UTC.

    SQLite has no way to preserve tzinfo across a round trip — a tz-aware
    datetime written to a plain DateTime column comes back naive on the next
    read, regardless of what was originally passed in. Rather than let that
    surface as random naive-vs-aware comparison crashes, this project's
    convention is: every datetime touching the Event table is naive-but-
    always-UTC. Anything that constructs or compares against Event
    datetimes should pass through this at the boundary.
    """
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.replace(tzinfo=None)
