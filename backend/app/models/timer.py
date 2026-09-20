from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel

from ..time_utils import to_naive_utc


def _now() -> datetime:
    return to_naive_utc(datetime.now(timezone.utc))


class Timer(SQLModel, table=True):
    """A countdown timer, an alarm, or a stopwatch (`kind`).

    Everything is stored as absolute instants (naive UTC, per time_utils.py)
    rather than "seconds left", so a running timer or alarm keeps counting
    correctly across a backend restart or reboot — it simply finds itself due
    (or overdue) at the next tick.

    state: running | paused | ringing. A finished timer/alarm is `ringing`
    until it is dismissed (or snoozed, which sends it back to `running`).
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str  # "timer" | "alarm" | "stopwatch"
    label: str = ""
    state: str = "running"
    created_at: datetime = Field(default_factory=_now)

    # Timers and alarms: the instant it goes off. None while a timer is paused.
    due_at: Optional[datetime] = None
    ring_started_at: Optional[datetime] = None  # lets the chime give up after a while

    # Timers: the original length, and what was left when it was paused.
    duration_seconds: Optional[int] = None
    paused_remaining_seconds: Optional[float] = None

    # Alarms: local wall-clock time "HH:MM" (24h) and how it repeats.
    alarm_time: Optional[str] = None
    repeat: str = "none"  # "none" | "daily" | "weekdays"

    # Stopwatches: time accumulated before the current run, and when that run began.
    elapsed_seconds: float = 0.0
    started_at: Optional[datetime] = None  # None while paused
