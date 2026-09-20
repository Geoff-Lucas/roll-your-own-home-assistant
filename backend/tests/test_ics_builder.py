from datetime import date, datetime

import icalendar

from app.models import Event
from app.sync.ics_builder import build_ics, new_uid


def test_new_uid_is_unique_and_stable_format():
    a, b = new_uid(), new_uid()
    assert a != b
    assert a.endswith("@home-organizer.local")


def test_build_ics_timed_event_round_trips_via_icalendar():
    event = Event(
        account_id=1,
        uid="abc-123@home-organizer.local",
        title="Dentist",
        description="Annual checkup",
        location="123 Main St",
        all_day=False,
        timezone="America/New_York",
        start_time=datetime(2026, 7, 15, 18, 0),  # naive-UTC, per Event's convention
        end_time=datetime(2026, 7, 15, 19, 0),
    )

    ics_text = build_ics(event)
    parsed = icalendar.Calendar.from_ical(ics_text)
    vevents = list(parsed.walk("VEVENT"))

    assert len(vevents) == 1
    vevent = vevents[0]
    assert str(vevent["UID"]) == "abc-123@home-organizer.local"
    assert str(vevent["SUMMARY"]) == "Dentist"
    assert str(vevent["DESCRIPTION"]) == "Annual checkup"
    assert str(vevent["LOCATION"]) == "123 Main St"
    # 18:00 UTC -> 14:00 EDT
    assert vevent["DTSTART"].dt.hour == 14
    assert str(vevent["DTSTART"].params.get("TZID")) == "America/New_York"


def test_build_ics_all_day_event_uses_date_values():
    event = Event(
        account_id=1,
        uid="allday-1@home-organizer.local",
        title="Anniversary",
        all_day=True,
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 21),
    )

    ics_text = build_ics(event)
    vevent = next(iter(icalendar.Calendar.from_ical(ics_text).walk("VEVENT")))

    assert vevent["DTSTART"].dt == date(2026, 7, 20)
    assert vevent["DTEND"].dt == date(2026, 7, 21)
    assert not isinstance(vevent["DTSTART"].dt, datetime)


def test_build_ics_without_optional_fields_omits_them():
    event = Event(
        account_id=1,
        uid="bare-1@home-organizer.local",
        title="Quick note",
        all_day=True,
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 21),
    )

    ics_text = build_ics(event)
    vevent = next(iter(icalendar.Calendar.from_ical(ics_text).walk("VEVENT")))

    assert vevent.get("DESCRIPTION") is None
    assert vevent.get("LOCATION") is None
