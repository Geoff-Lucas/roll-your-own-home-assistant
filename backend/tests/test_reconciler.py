from datetime import datetime, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Event
from app.sync.reconciler import reconcile_account_events


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def make_event(**overrides) -> Event:
    defaults = dict(
        account_id=1,
        uid="event-1@example.com",
        title="Test event",
        all_day=False,
        start_time=datetime(2026, 7, 15, 18, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 7, 15, 19, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Event(**defaults)


WINDOW_START = datetime(2026, 7, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 7, 31, tzinfo=timezone.utc)


def test_new_events_are_inserted(session):
    reconcile_account_events(session, account_id=1, parsed_events=[make_event()], window_start=WINDOW_START, window_end=WINDOW_END)

    rows = session.exec(select(Event)).all()
    assert len(rows) == 1
    assert rows[0].title == "Test event"


def test_existing_event_is_updated_in_place(session):
    reconcile_account_events(session, account_id=1, parsed_events=[make_event(title="Original")], window_start=WINDOW_START, window_end=WINDOW_END)
    original_id = session.exec(select(Event)).one().id

    reconcile_account_events(session, account_id=1, parsed_events=[make_event(title="Renamed")], window_start=WINDOW_START, window_end=WINDOW_END)

    rows = session.exec(select(Event)).all()
    assert len(rows) == 1
    assert rows[0].id == original_id
    assert rows[0].title == "Renamed"


def test_event_removed_upstream_and_in_window_is_deleted(session):
    reconcile_account_events(session, account_id=1, parsed_events=[make_event()], window_start=WINDOW_START, window_end=WINDOW_END)

    # server no longer returns it in this window
    reconcile_account_events(session, account_id=1, parsed_events=[], window_start=WINDOW_START, window_end=WINDOW_END)

    assert session.exec(select(Event)).all() == []


def test_event_outside_fetched_window_is_left_untouched(session):
    # an event cached previously, e.g. from a prior sync with a wider window,
    # that falls outside *this* sync's window must not be touched, since we
    # have no evidence from this fetch that it was actually removed upstream
    far_future = make_event(
        uid="far-future@example.com",
        start_time=datetime(2027, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2027, 1, 1, 1, 0, tzinfo=timezone.utc),
    )
    session.add(far_future)
    session.commit()

    reconcile_account_events(session, account_id=1, parsed_events=[], window_start=WINDOW_START, window_end=WINDOW_END)

    rows = session.exec(select(Event)).all()
    assert len(rows) == 1
    assert rows[0].uid == "far-future@example.com"


def test_locally_created_event_survives_the_next_sync_without_id_churn(session):
    # Regression test for a bug caught live against a real Google account:
    # a locally created event whose recurrence_id matches what a fresh sync
    # would compute for it (see routers/events.py _compute_recurrence_id)
    # must be recognized as the *same* row on the next sync, not deleted and
    # replaced under a new id.
    locally_created = make_event(recurrence_id="2026-07-15T18:00:00")
    reconcile_account_events(
        session, account_id=1, parsed_events=[locally_created], window_start=WINDOW_START, window_end=WINDOW_END
    )
    original_id = session.exec(select(Event)).one().id

    # a subsequent sync fetches this same event back from the server — same
    # uid, same recurrence_id (an unparsed, non-recurring event's
    # recurrence_id from recurring_ical_events is always its own instant)
    synced_back = make_event(recurrence_id="2026-07-15T18:00:00")
    reconcile_account_events(
        session, account_id=1, parsed_events=[synced_back], window_start=WINDOW_START, window_end=WINDOW_END
    )

    rows = session.exec(select(Event)).all()
    assert len(rows) == 1
    assert rows[0].id == original_id  # updated in place, not deleted + recreated


def test_locally_created_event_without_recurrence_id_churns_on_next_sync(session):
    # The bug itself, kept as a test so it can't silently come back: an
    # event created with recurrence_id=None does NOT match the recurrence_id
    # a real sync assigns the same event, so it gets deleted and replaced.
    # This documents why _compute_recurrence_id in routers/events.py exists.
    locally_created = make_event(recurrence_id=None)
    reconcile_account_events(
        session, account_id=1, parsed_events=[locally_created], window_start=WINDOW_START, window_end=WINDOW_END
    )
    original_id = session.exec(select(Event)).one().id

    synced_back = make_event(recurrence_id="2026-07-15T18:00:00")
    reconcile_account_events(
        session, account_id=1, parsed_events=[synced_back], window_start=WINDOW_START, window_end=WINDOW_END
    )

    rows = session.exec(select(Event)).all()
    assert len(rows) == 1
    assert rows[0].id != original_id  # churned — this is the bug, not the fix


def test_recurring_occurrences_keyed_by_uid_and_recurrence_id(session):
    occurrence_a = make_event(recurrence_id="2026-07-07T18:00:00+00:00", rrule="FREQ=WEEKLY")
    occurrence_b = make_event(
        recurrence_id="2026-07-14T18:00:00+00:00",
        rrule="FREQ=WEEKLY",
        start_time=datetime(2026, 7, 14, 18, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 7, 14, 19, 0, tzinfo=timezone.utc),
    )

    reconcile_account_events(
        session, account_id=1, parsed_events=[occurrence_a, occurrence_b], window_start=WINDOW_START, window_end=WINDOW_END
    )

    rows = session.exec(select(Event)).all()
    assert len(rows) == 2
    assert {r.recurrence_id for r in rows} == {"2026-07-07T18:00:00+00:00", "2026-07-14T18:00:00+00:00"}
