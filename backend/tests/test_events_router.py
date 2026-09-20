from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.models import Account, Event
from app.routers import events as events_module


@pytest.fixture
def setup(monkeypatch):
    # A standalone app with just the events router — deliberately bypasses
    # main.py's lifespan (which starts the background sync loop against the
    # real on-disk DB) so these tests stay hermetic.
    # StaticPool keeps a single underlying connection alive for the whole
    # engine — plain sqlite:// otherwise hands out a fresh, separate
    # in-memory database per connection, so the tables created below
    # wouldn't be visible to the requests TestClient makes afterward.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    test_app = FastAPI()
    test_app.include_router(events_module.router)
    test_app.dependency_overrides[get_session] = override_get_session

    with Session(engine) as session:
        session.add(
            Account(id=1, provider="caldav", display_name="Test", person_name="Geoff", caldav_url="https://example.com/dav")
        )
        session.add(Account(id=2, provider="caldav", display_name="No CalDAV", person_name="NoOne"))
        session.commit()

    # Stub out the CalDAV transport entirely — these are router/wiring
    # tests, not a substitute for live CalDAV verification.
    caldav_calls = {}
    monkeypatch.setattr(events_module, "create_event_on_server", lambda account, ical: caldav_calls.setdefault("created_ical", ical))
    monkeypatch.setattr(
        events_module, "update_event_on_server", lambda account, uid, search_window, ical: caldav_calls.setdefault("updated_ical", ical)
    )
    monkeypatch.setattr(
        events_module, "delete_event_on_server", lambda account, uid, search_window: caldav_calls.setdefault("deleted_uid", uid)
    )

    return TestClient(test_app), engine, caldav_calls


def make_event_payload(**overrides):
    payload = {
        "account_id": 1,
        "title": "Dentist",
        "start_time": "2026-07-15T14:00:00",
        "end_time": "2026-07-15T15:00:00",
    }
    payload.update(overrides)
    return payload


def test_create_event_writes_to_caldav_and_local_cache(setup):
    client, _, caldav_calls = setup

    res = client.post("/events", json=make_event_payload())
    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "Dentist"
    assert body["uid"].endswith("@home-organizer.local")
    assert "created_ical" in caldav_calls


def test_create_event_rejects_account_without_caldav(setup):
    client, _, _ = setup
    res = client.post("/events", json=make_event_payload(account_id=2))
    assert res.status_code == 400


def test_create_event_rejects_unknown_account(setup):
    client, _, _ = setup
    res = client.post("/events", json=make_event_payload(account_id=999))
    assert res.status_code == 404


def test_update_event_round_trips_to_caldav(setup):
    client, _, caldav_calls = setup
    created = client.post("/events", json=make_event_payload()).json()

    res = client.patch(f"/events/{created['id']}", json={"title": "Dentist (rescheduled)"})
    assert res.status_code == 200
    assert res.json()["title"] == "Dentist (rescheduled)"
    assert "updated_ical" in caldav_calls


def _seed_recurring_event(engine) -> int:
    with Session(engine) as session:
        event = Event(
            account_id=1,
            uid="recurring-1@example.com",
            title="Trash day",
            all_day=False,
            start_time=datetime(2026, 7, 14, 11, 0),
            end_time=datetime(2026, 7, 14, 11, 15),
            rrule="FREQ=WEEKLY;BYDAY=TU",
            recurrence_id="2026-07-14T11:00:00",
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        return event.id


def test_update_rejects_recurring_event(setup):
    client, engine, caldav_calls = setup
    event_id = _seed_recurring_event(engine)

    res = client.patch(f"/events/{event_id}", json={"title": "Nope"})

    assert res.status_code == 400
    assert not caldav_calls


def test_delete_rejects_recurring_event(setup):
    client, engine, caldav_calls = setup
    event_id = _seed_recurring_event(engine)

    res = client.delete(f"/events/{event_id}")

    assert res.status_code == 400
    assert not caldav_calls


def test_delete_event_round_trips_to_caldav(setup):
    client, _, caldav_calls = setup
    created = client.post("/events", json=make_event_payload()).json()

    res = client.delete(f"/events/{created['id']}")
    assert res.status_code == 204
    assert caldav_calls["deleted_uid"] == created["uid"]
    assert client.get("/events").json() == []


def test_delete_unknown_event_returns_404(setup):
    client, _, _ = setup
    res = client.delete("/events/999")
    assert res.status_code == 404


def test_create_event_sets_recurrence_id_to_the_instant(setup):
    # Caught live against a real Google account: without this, a freshly
    # created event's recurrence_id (None) doesn't match what the next sync
    # cycle computes for the same event (its own instant, per
    # recurring_ical_events — see sync/ics_parser.py), so the reconciler
    # treats it as a different row and silently swaps it out from under its id.
    client, _, _ = setup

    timed = client.post("/events", json=make_event_payload()).json()
    assert timed["recurrence_id"] == "2026-07-15T14:00:00"

    all_day = client.post(
        "/events", json=make_event_payload(all_day=True, start_time=None, end_time=None, start_date="2026-08-01", end_date="2026-08-02")
    ).json()
    assert all_day["recurrence_id"] == "2026-08-01"


def test_update_event_recomputes_recurrence_id_when_time_changes(setup):
    client, _, _ = setup
    created = client.post("/events", json=make_event_payload()).json()
    assert created["recurrence_id"] == "2026-07-15T14:00:00"

    updated = client.patch(
        f"/events/{created['id']}", json={"start_time": "2026-07-16T09:00:00", "end_time": "2026-07-16T10:00:00"}
    ).json()

    assert updated["recurrence_id"] == "2026-07-16T09:00:00"
