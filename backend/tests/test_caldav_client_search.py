from datetime import datetime, timedelta

import pytest

from app.models import Event
from app.sync import caldav_client


def make_event(**overrides):
    defaults = dict(
        account_id=1,
        uid="e1@example.com",
        title="Test",
        all_day=False,
        start_time=datetime(2026, 7, 15, 14, 0),
        end_time=datetime(2026, 7, 15, 15, 0),
    )
    defaults.update(overrides)
    return Event(**defaults)


def test_event_search_window_timed_event_has_one_day_buffer():
    event = make_event()
    start, end = caldav_client.event_search_window(event)
    assert start == datetime(2026, 7, 14, 14, 0)
    assert end == datetime(2026, 7, 16, 15, 0)


def test_event_search_window_all_day_event():
    from datetime import date

    event = make_event(all_day=True, start_time=None, end_time=None, start_date=date(2026, 8, 1), end_date=date(2026, 8, 2))
    start, end = caldav_client.event_search_window(event)
    assert start == datetime(2026, 7, 31, 0, 0)
    assert end == datetime(2026, 8, 3, 0, 0)


class FakeCalendarObject:
    def __init__(self, data):
        self.data = data
        self.saved = False
        self.deleted = False

    def save(self):
        self.saved = True

    def delete(self):
        self.deleted = True


OTHER_EVENT_ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:other@example.com
DTSTART:20260715T140000Z
DTEND:20260715T150000Z
SUMMARY:Someone else's event
END:VEVENT
END:VCALENDAR
"""

TARGET_EVENT_ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:target@example.com
DTSTART:20260715T140000Z
DTEND:20260715T150000Z
SUMMARY:The one we want
END:VEVENT
END:VCALENDAR
"""


def test_find_calendar_object_matches_by_uid_not_just_position():
    # This is the exact behavior that broke against a real Google account:
    # a bounded search can return many events in range (Google doesn't
    # filter server-side by uid), so matching must happen client-side.
    calendar = type(
        "FakeCalendar",
        (),
        {"search": lambda self, **kwargs: [FakeCalendarObject(OTHER_EVENT_ICS), FakeCalendarObject(TARGET_EVENT_ICS)]},
    )()

    found = caldav_client._find_calendar_object(
        calendar, "target@example.com", datetime(2026, 7, 14), datetime(2026, 7, 16)
    )

    assert found.data == TARGET_EVENT_ICS


def test_find_calendar_object_raises_when_uid_not_present():
    calendar = type("FakeCalendar", (), {"search": lambda self, **kwargs: [FakeCalendarObject(OTHER_EVENT_ICS)]})()

    with pytest.raises(caldav_client.CalDAVError, match="not found"):
        caldav_client._find_calendar_object(calendar, "missing@example.com", datetime(2026, 7, 14), datetime(2026, 7, 16))


def test_update_event_on_server_searches_then_saves(monkeypatch):
    target = FakeCalendarObject(TARGET_EVENT_ICS)
    monkeypatch.setattr(caldav_client, "_first_calendar", lambda account: "fake-calendar")
    monkeypatch.setattr(caldav_client, "_find_calendar_object", lambda calendar, uid, start, end: target)

    caldav_client.update_event_on_server(
        account=None, uid="target@example.com", search_window=(datetime(2026, 7, 14), datetime(2026, 7, 16)), ical_text="NEW ICS"
    )

    assert target.data == "NEW ICS"
    assert target.saved is True


def test_delete_event_on_server_searches_then_deletes(monkeypatch):
    target = FakeCalendarObject(TARGET_EVENT_ICS)
    monkeypatch.setattr(caldav_client, "_first_calendar", lambda account: "fake-calendar")
    monkeypatch.setattr(caldav_client, "_find_calendar_object", lambda calendar, uid, start, end: target)

    caldav_client.delete_event_on_server(
        account=None, uid="target@example.com", search_window=(datetime(2026, 7, 14), datetime(2026, 7, 16))
    )

    assert target.deleted is True
