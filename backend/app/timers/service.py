"""Timers, alarms and stopwatches: creating them, moving them between states,
and describing them for the UI.

Kept free of I/O beyond the database session, and every function that depends
on "now" takes it as an argument, so the logic (especially alarm scheduling
across midnight, weekdays and daylight saving) can be tested with a fake clock.
The voice commands built later call these same functions.
"""

import re
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from ..config import settings
from ..models import Timer
from ..time_utils import local_tz, to_naive_utc  # noqa: F401  local_tz is also used via service.local_tz()

MAX_TIMER_SECONDS = 99 * 3600 + 59 * 60 + 59
REPEATS = ("none", "daily", "weekdays")
_ALARM_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _now() -> datetime:
    return to_naive_utc(datetime.now(timezone.utc))


def parse_alarm_time(text: str) -> tuple[int, int]:
    match = _ALARM_TIME.match(text or "")
    if not match:
        raise ValueError("Alarm time must be HH:MM in 24-hour time")
    return int(match.group(1)), int(match.group(2))


def next_alarm_due(alarm_time: str, repeat: str, after: datetime) -> datetime:
    """The next instant (naive UTC) strictly after `after` that the wall clock
    reads `alarm_time` locally — skipping weekends for "weekdays". Built with
    date arithmetic in the local zone rather than adding 24h, so an alarm set
    for 07:00 still rings at 07:00 on the morning the clocks change."""
    hour, minute = parse_alarm_time(alarm_time)
    tz = local_tz()
    local_after = after.replace(tzinfo=timezone.utc).astimezone(tz)
    day = local_after.date()
    for _ in range(9):  # at most a weekend plus a day
        candidate = datetime.combine(day, time(hour, minute), tzinfo=tz)
        if candidate > local_after and (repeat != "weekdays" or candidate.weekday() < 5):
            return to_naive_utc(candidate)
        day += timedelta(days=1)
    raise RuntimeError("unreachable: no alarm occurrence within nine days")


# --- creating ---------------------------------------------------------------


def create_timer(session: Session, seconds: int, label: str = "", now: Optional[datetime] = None) -> Timer:
    if not 1 <= seconds <= MAX_TIMER_SECONDS:
        raise ValueError("A timer must be between 1 second and 99 hours")
    now = now or _now()
    timer = Timer(kind="timer", label=label.strip(), state="running", duration_seconds=seconds)
    timer.due_at = now + timedelta(seconds=seconds)
    return _save(session, timer)


def create_alarm(
    session: Session, alarm_time: str, repeat: str = "none", label: str = "", now: Optional[datetime] = None
) -> Timer:
    if repeat not in REPEATS:
        raise ValueError(f"repeat must be one of {', '.join(REPEATS)}")
    now = now or _now()
    timer = Timer(kind="alarm", label=label.strip(), state="running", alarm_time=alarm_time, repeat=repeat)
    timer.due_at = next_alarm_due(alarm_time, repeat, now)
    return _save(session, timer)


def create_stopwatch(session: Session, label: str = "", now: Optional[datetime] = None) -> Timer:
    now = now or _now()
    return _save(session, Timer(kind="stopwatch", label=label.strip(), state="running", started_at=now))


def _save(session: Session, timer: Timer) -> Timer:
    session.add(timer)
    session.commit()
    session.refresh(timer)
    return timer


def get(session: Session, timer_id: int) -> Timer:
    timer = session.get(Timer, timer_id)
    if timer is None:
        raise LookupError(f"No timer with id {timer_id}")
    return timer


# --- moving between states --------------------------------------------------


def pause(session: Session, timer: Timer, now: Optional[datetime] = None) -> Timer:
    now = now or _now()
    if timer.state != "running" or timer.kind not in ("timer", "stopwatch"):
        raise ValueError("Only a running timer or stopwatch can be paused")
    if timer.kind == "timer":
        timer.paused_remaining_seconds = max(0.0, (timer.due_at - now).total_seconds())
        timer.due_at = None
    else:
        timer.elapsed_seconds += (now - timer.started_at).total_seconds()
        timer.started_at = None
    timer.state = "paused"
    return _save(session, timer)


def resume(session: Session, timer: Timer, now: Optional[datetime] = None) -> Timer:
    now = now or _now()
    if timer.state != "paused":
        raise ValueError("Only a paused timer or stopwatch can be resumed")
    if timer.kind == "timer":
        timer.due_at = now + timedelta(seconds=timer.paused_remaining_seconds or 0)
        timer.paused_remaining_seconds = None
    else:
        timer.started_at = now
    timer.state = "running"
    return _save(session, timer)


def reset_stopwatch(session: Session, timer: Timer) -> Timer:
    if timer.kind != "stopwatch":
        raise ValueError("Only a stopwatch can be reset")
    timer.elapsed_seconds = 0.0
    timer.started_at = None
    timer.state = "paused"
    return _save(session, timer)


def snooze(session: Session, timer: Timer, minutes: int, now: Optional[datetime] = None) -> Timer:
    """Silence a ringing timer or alarm and have it go off again in `minutes`."""
    now = now or _now()
    if timer.state != "ringing":
        raise ValueError("Only a ringing timer or alarm can be snoozed")
    if not 1 <= minutes <= 120:
        raise ValueError("Snooze must be between 1 and 120 minutes")
    timer.due_at = now + timedelta(minutes=minutes)
    timer.ring_started_at = None
    timer.state = "running"
    return _save(session, timer)


def dismiss(session: Session, timer: Timer, now: Optional[datetime] = None) -> Optional[Timer]:
    """Acknowledge a ringing timer or alarm. A repeating alarm goes back to
    waiting for its next occurrence; anything else is finished and removed.
    Returns the surviving row, or None if it was removed."""
    now = now or _now()
    if timer.state != "ringing":
        raise ValueError("Only a ringing timer or alarm can be dismissed")
    if timer.kind == "alarm" and timer.repeat != "none":
        timer.due_at = next_alarm_due(timer.alarm_time, timer.repeat, now)
        timer.ring_started_at = None
        timer.state = "running"
        return _save(session, timer)
    session.delete(timer)
    session.commit()
    return None


def delete(session: Session, timer: Timer) -> None:
    """Cancel/remove regardless of state (including a repeating alarm for good)."""
    session.delete(timer)
    session.commit()


# --- the clock ---------------------------------------------------------------


def tick(session: Session, now: Optional[datetime] = None) -> list[Timer]:
    """Move anything that has come due to `ringing`; returns those that just did.
    Also catches things that came due while the backend was down."""
    now = now or _now()
    due = session.exec(select(Timer).where(Timer.state == "running", Timer.due_at <= now)).all()
    for timer in due:
        timer.state = "ringing"
        timer.ring_started_at = now
        session.add(timer)
    if due:
        session.commit()
    return list(due)


def ringing_audibly(timers: list[Timer], now: datetime) -> bool:
    """Is anything ringing recently enough that the chime should keep sounding?
    (It gives up after timer_ring_max_seconds; the on-screen alert stays.)"""
    limit = timedelta(seconds=settings.timer_ring_max_seconds)
    return any(t.state == "ringing" and t.ring_started_at is not None and now - t.ring_started_at < limit for t in timers)


# --- describing --------------------------------------------------------------

_STATE_ORDER = {"ringing": 0, "running": 1, "paused": 2}


def _sort_key(timer: Timer):
    # Ringing first; then whatever goes off soonest; stopwatches last.
    soonest = timer.due_at or datetime.max
    return (_STATE_ORDER.get(timer.state, 3), timer.kind == "stopwatch", soonest, timer.id or 0)


def list_all(session: Session) -> list[Timer]:
    return sorted(session.exec(select(Timer)).all(), key=_sort_key)


def describe(timer: Timer, now: Optional[datetime] = None) -> dict:
    """What the UI needs, with times as plain seconds so it can count down
    locally without caring about clock zones or skew."""
    now = now or _now()
    remaining = elapsed = None
    if timer.kind == "stopwatch":
        elapsed = timer.elapsed_seconds + ((now - timer.started_at).total_seconds() if timer.started_at else 0.0)
    elif timer.state == "paused":
        remaining = timer.paused_remaining_seconds
    elif timer.due_at is not None:
        remaining = max(0.0, (timer.due_at - now).total_seconds())
    return {
        "id": timer.id,
        "kind": timer.kind,
        "label": timer.label,
        "state": timer.state,
        "duration_seconds": timer.duration_seconds,
        "alarm_time": timer.alarm_time,
        "repeat": timer.repeat,
        "remaining_seconds": remaining,
        "elapsed_seconds": elapsed,
    }
