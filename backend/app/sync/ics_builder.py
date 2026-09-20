import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import icalendar

from ..models import Event


def new_uid() -> str:
    return f"{uuid.uuid4()}@home-organizer.local"


def build_ics(event: Event) -> str:
    """Build a standalone iCalendar document for a single (non-recurring)
    event, suitable for creating or replacing a CalDAV resource.

    Deliberately doesn't handle RRULE/RECURRENCE-ID — write-back for
    recurring events isn't supported yet (see routers/events.py), so this
    only ever needs to represent one concrete VEVENT.
    """
    calendar = icalendar.Calendar()
    calendar.add("prodid", "-//Home Organizer//home-organizer.local//")
    calendar.add("version", "2.0")

    vevent = icalendar.Event()
    vevent.add("uid", event.uid)
    vevent.add("summary", event.title)
    vevent.add("dtstamp", datetime.now(timezone.utc))
    if event.description:
        vevent.add("description", event.description)
    if event.location:
        vevent.add("location", event.location)

    if event.all_day:
        vevent.add("dtstart", event.start_date)
        vevent.add("dtend", event.end_date)
    else:
        # start_time/end_time are stored naive-but-UTC (see time_utils.to_naive_utc);
        # reattach UTC then render in the event's own timezone for a more
        # readable wire format, falling back to plain UTC if unknown.
        tz = ZoneInfo(event.timezone) if event.timezone else timezone.utc
        start_utc = event.start_time.replace(tzinfo=timezone.utc)
        end_utc = event.end_time.replace(tzinfo=timezone.utc)
        vevent.add("dtstart", start_utc.astimezone(tz))
        vevent.add("dtend", end_utc.astimezone(tz))

    calendar.add_component(vevent)
    return calendar.to_ical().decode()
