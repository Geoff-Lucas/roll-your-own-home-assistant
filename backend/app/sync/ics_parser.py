from datetime import datetime
from typing import Dict, List, Optional

import icalendar
import recurring_ical_events

from ..models import Event
from ..time_utils import to_naive_utc


def _normalize(value) -> str:
    """ISO-format a date or datetime, normalizing datetimes to naive UTC
    first (see time_utils.to_naive_utc) so recurrence_id strings are always
    directly comparable regardless of the source event's timezone."""
    if isinstance(value, datetime):
        return to_naive_utc(value).isoformat()
    return value.isoformat()


def parse_ics_resource(
    raw_ics: bytes,
    account_id: int,
    window_start: datetime,
    window_end: datetime,
) -> List[Event]:
    """Parse one CalDAV resource — a VCALENDAR that may contain a single
    VEVENT, or a recurring series (a master VEVENT with an RRULE plus any
    per-occurrence override VEVENTs sharing its UID) — into concrete, unsaved
    Event rows covering [window_start, window_end].

    Recurrence expansion (RRULE/EXDATE/RECURRENCE-ID overrides, timezone
    handling) is delegated to `recurring_ical_events` rather than hand-rolled:
    it's a mature library built specifically for this, and correctly handles
    edge cases (DST transitions, BYDAY/BYSETPOS, overridden occurrences) that
    are easy to get subtly wrong by hand. This function only ever returns
    concrete occurrences, never an unbounded series.
    """
    calendar = icalendar.Calendar.from_ical(raw_ics)
    occurrences = recurring_ical_events.of(calendar, keep_recurrence_attributes=True).between(
        window_start, window_end
    )

    # A series' RRULE is only preserved by the library on generated
    # occurrences, not on the ones an override replaced. Propagate it across
    # every occurrence sharing a UID so "is this part of a series" is a
    # simple per-row check regardless of which occurrence is being looked at.
    rrule_by_uid: Dict[str, str] = {}
    for occ in occurrences:
        rrule_prop = occ.get("RRULE")
        if rrule_prop is not None:
            rrule_by_uid[str(occ.get("UID"))] = rrule_prop.to_ical().decode()

    events: List[Event] = []
    for occ in occurrences:
        uid = str(occ.get("UID"))
        title = str(occ.get("SUMMARY", "")) or "(untitled)"
        description = str(occ.get("DESCRIPTION")) if occ.get("DESCRIPTION") else None
        location = str(occ.get("LOCATION")) if occ.get("LOCATION") else None

        dtstart_prop = occ.get("DTSTART")
        dtend_prop = occ.get("DTEND")
        dtstart = dtstart_prop.dt
        # No DTEND (rare, e.g. a reminder-only VEVENT with no DURATION either):
        # treat as a zero-length instant rather than erroring.
        dtend = dtend_prop.dt if dtend_prop else dtstart
        all_day = not isinstance(dtstart, datetime)

        recurrence_id_prop = occ.get("RECURRENCE-ID")
        recurrence_id: Optional[str] = _normalize(recurrence_id_prop.dt) if recurrence_id_prop else None

        event = Event(
            account_id=account_id,
            uid=uid,
            title=title,
            description=description,
            location=location,
            all_day=all_day,
            rrule=rrule_by_uid.get(uid),
            recurrence_id=recurrence_id,
        )
        if all_day:
            event.start_date = dtstart
            event.end_date = dtend
        else:
            event.timezone = dtstart_prop.params.get("TZID") if hasattr(dtstart_prop, "params") else None
            event.start_time = dtstart  # normalized to naive UTC by Event's validator
            event.end_time = dtend

        events.append(event)

    return events
