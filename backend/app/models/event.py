from datetime import date, datetime, timezone
from typing import Optional

from pydantic import ConfigDict, field_validator
from sqlmodel import Field, SQLModel

from ..time_utils import to_naive_utc


class Event(SQLModel, table=True):
    """A concrete calendar occurrence, cached locally and reconciled against
    CalDAV by the sync worker (app/sync/).

    Timed events store UTC instants in start_time/end_time plus the original
    IANA timezone. All-day events store dates only (start_date/end_date,
    end exclusive per RFC 5545) — never midnight timestamps, which shift
    across DST/timezone boundaries.

    Recurrence (RRULE/EXDATE/RECURRENCE-ID overrides) is expanded into
    concrete rows by the sync worker using the `recurring_ical_events`
    library — this table only ever holds actual occurrences within the
    synced window, never an infinite series. `rrule` is a denormalized
    marker copied onto every occurrence of a series purely so "is this part
    of a recurring series" is a simple per-row check; `recurrence_id` is the
    occurrence's original scheduled instant (stable even if an override
    moved it) and is what makes a row unique together with (account_id, uid).

    start_time/end_time/last_synced_at are normalized to naive-but-UTC on
    construction (see time_utils.to_naive_utc) because SQLite can't preserve
    tzinfo across a round trip — code that compares against these fields
    (the sync reconciler, the events API) must normalize its own comparison
    values the same way rather than assume they're tz-aware.
    """

    # Pydantic only runs field validators at construction time by default —
    # both the sync reconciler's upsert and the PATCH /events endpoint
    # assign fields onto an already-constructed row, which would otherwise
    # silently skip normalization. validate_assignment closes that gap.
    model_config = ConfigDict(validate_assignment=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    # Deleting an account deletes its cached events; they're only a copy of the
    # server's, and come back with a sync if the account is linked again.
    account_id: int = Field(foreign_key="account.id", index=True, ondelete="CASCADE")
    uid: str = Field(index=True)  # CalDAV event UID, shared across all occurrences of a series

    title: str
    description: Optional[str] = None
    location: Optional[str] = None

    # Timed events (all_day=False): UTC instants + original timezone.
    start_time: Optional[datetime] = Field(default=None, index=True)
    end_time: Optional[datetime] = Field(default=None, index=True)
    timezone: Optional[str] = None  # IANA name, e.g. "America/New_York"

    # All-day events (all_day=True): dates only, end_date exclusive.
    all_day: bool = False
    start_date: Optional[date] = Field(default=None, index=True)
    end_date: Optional[date] = Field(default=None, index=True)

    rrule: Optional[str] = None  # informational only; see docstring
    recurrence_id: Optional[str] = None  # ISO datetime/date of this occurrence's original instant

    last_synced_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Prep reminders (see app/reminders/detection.py): reminder_lead_days set
    # means "manually flagged" and overrides keyword auto-detection entirely;
    # left unset, the reminders endpoint falls back to matching the title
    # against a keyword list (birthday, anniversary, etc.). reminder_dismissed
    # is the "make it go away" mechanism regardless of which path produced it
    # — per concrete occurrence row, so dismissing this year's birthday
    # reminder doesn't touch next year's (a separate row, per the recurrence
    # design above).
    reminder_lead_days: Optional[int] = None
    reminder_text: Optional[str] = None
    reminder_dismissed: bool = False

    @field_validator("start_time", "end_time", "last_synced_at", mode="before")
    @classmethod
    def _normalize_datetime(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        return to_naive_utc(value)
