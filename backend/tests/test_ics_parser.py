from datetime import date, datetime, timezone
from pathlib import Path

from app.sync.ics_parser import parse_ics_resource

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_simple_timed_event_normalized_to_utc():
    window_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 7, 31, tzinfo=timezone.utc)

    events = parse_ics_resource(load("simple_timed.ics"), account_id=1, window_start=window_start, window_end=window_end)

    assert len(events) == 1
    event = events[0]
    assert event.title == "Dentist"
    assert event.location == "123 Main St"
    assert event.all_day is False
    assert event.timezone == "America/New_York"
    # 14:00 EDT (UTC-4) -> 18:00 UTC, stored naive (SQLite can't keep tzinfo)
    assert event.start_time == datetime(2026, 7, 15, 18, 0)
    assert event.end_time == datetime(2026, 7, 15, 19, 0)
    assert event.rrule is None
    # recurring_ical_events assigns every occurrence a RECURRENCE-ID (even a
    # non-recurring single event), equal to its own instant — it doubles as
    # a stable per-row identity regardless of whether the event recurs.
    assert event.recurrence_id == "2026-07-15T18:00:00"


def test_all_day_event_stores_dates_not_datetimes():
    window_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 7, 31, tzinfo=timezone.utc)

    events = parse_ics_resource(load("all_day.ics"), account_id=1, window_start=window_start, window_end=window_end)

    assert len(events) == 1
    event = events[0]
    assert event.all_day is True
    assert event.start_date == date(2026, 7, 20)
    assert event.end_date == date(2026, 7, 21)
    assert event.start_time is None
    assert event.end_time is None


def test_recurring_series_expands_skips_exdate_and_honors_override():
    window_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 8, 15, tzinfo=timezone.utc)

    events = parse_ics_resource(
        load("recurring_with_override.ics"), account_id=1, window_start=window_start, window_end=window_end
    )
    events.sort(key=lambda e: e.start_time)

    # Weekly Tuesdays 7/14, 7/21 (overridden), 7/28, [8/4 excluded], 8/11
    assert len(events) == 4
    assert [e.start_time.date().isoformat() for e in events] == [
        "2026-07-14",
        "2026-07-21",
        "2026-07-28",
        "2026-08-11",
    ]

    generated, overridden, generated2, generated3 = events

    # every occurrence — generated or overridden — carries the series' rrule
    for e in events:
        assert e.rrule == "FREQ=WEEKLY;BYDAY=TU"
        assert e.uid == "recur-event-1@example.com"

    assert generated.title == "Trash day"
    assert generated.start_time == datetime(2026, 7, 14, 11, 0)

    # override moved the time and changed the title, but recurrence_id still
    # reflects the *original* scheduled instant, not the moved time
    assert overridden.title == "Trash day (delayed pickup)"
    assert overridden.start_time == datetime(2026, 7, 21, 12, 0)
    assert overridden.recurrence_id == "2026-07-21T11:00:00"
