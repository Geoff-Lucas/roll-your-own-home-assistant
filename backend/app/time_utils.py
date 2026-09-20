from datetime import datetime, timezone


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
