"""An event edited on the kiosk while a sync is fetching from the server.

The sync fetches first and reconciles afterwards, so without coordination a
local write that lands in between is judged against a stale copy of the
server: a new event looks "removed upstream" and is deleted, an edit is
reverted, and a deleted event is re-added. These tests pause a sync mid-fetch,
make the local change, then let the sync finish.
"""

import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.models import Account, Event
from app.routers import events as events_module
from app.sync import locks, worker

START = (datetime.now(timezone.utc) + timedelta(days=3)).replace(hour=14, minute=0, second=0, microsecond=0, tzinfo=None)


class PausedFetch:
    """Stands in for the CalDAV fetch; holds the sync mid-fetch until released."""

    def __init__(self, server_events):
        self.server_events = server_events  # what the server had when the fetch began
        self.started = threading.Event()
        self.release = threading.Event()

    def fetch(self, account, window_start, window_end):
        self.started.set()
        assert self.release.wait(timeout=5), "test never released the fetch"
        return ["ics"]

    def parse(self, raw, account_id, window_start, window_end):
        return [Event(**event.model_dump(exclude={"id"})) for event in self.server_events]


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=1, provider="caldav", display_name="Home", person_name="Geoff", caldav_url="https://dav.example"))
        session.commit()

    def override_get_session():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(events_module.router)
    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr(worker, "engine", engine)
    for name in ("create_event_on_server", "update_event_on_server", "delete_event_on_server"):
        monkeypatch.setattr(events_module, name, lambda *args: None)
    return TestClient(app), engine


def add_event(engine, **fields):
    event = Event(account_id=1, uid="uid-1", title="Dentist", start_time=START, end_time=START + timedelta(hours=1), **fields)
    event.recurrence_id = event.start_time.isoformat()
    with Session(engine) as session:
        session.add(event)
        session.commit()
        session.refresh(event)
        return event


def during_a_sync(monkeypatch, server_events, local_change):
    """Start a sync, make `local_change` while it's mid-fetch, then let it finish."""
    fetch = PausedFetch(server_events)
    monkeypatch.setattr(worker, "fetch_account_ics", fetch.fetch)
    monkeypatch.setattr(worker, "parse_ics_resource", fetch.parse)

    sync = threading.Thread(target=worker.sync_once)
    sync.start()
    assert fetch.started.wait(timeout=5)

    responses = []
    change = threading.Thread(target=lambda: responses.append(local_change()))
    change.start()
    change.join(timeout=0.3)  # give the change every chance to land mid-fetch
    fetch.release.set()
    sync.join(timeout=5)
    change.join(timeout=5)
    assert not sync.is_alive() and not change.is_alive()
    return responses[0]


def rows(engine):
    with Session(engine) as session:
        return session.exec(select(Event)).all()


def test_an_event_created_mid_sync_is_not_deleted_by_it(world, monkeypatch):
    client, engine = world
    payload = {
        "account_id": 1,
        "title": "Birthday dinner",
        "start_time": START.isoformat(),
        "end_time": (START + timedelta(hours=2)).isoformat(),
        "reminder_lead_days": 3,  # local-only: a re-add from the server wouldn't bring this back
    }

    response = during_a_sync(monkeypatch, server_events=[], local_change=lambda: client.post("/events", json=payload))

    assert response.status_code == 201
    (event,) = rows(engine)
    assert event.id == response.json()["id"] and event.reminder_lead_days == 3


def test_an_edit_made_mid_sync_is_not_reverted_by_it(world, monkeypatch):
    client, engine = world
    before = add_event(engine)

    response = during_a_sync(
        monkeypatch, server_events=[before], local_change=lambda: client.patch(f"/events/{before.id}", json={"title": "Dentist (moved)"})
    )

    assert response.status_code == 200
    assert [e.title for e in rows(engine)] == ["Dentist (moved)"]


def test_an_edit_waiting_on_a_sync_that_removed_the_event_gets_a_404(world, monkeypatch):
    client, engine = world
    before = add_event(engine)

    # The server no longer has it, so this sync removes it while the edit waits.
    response = during_a_sync(
        monkeypatch, server_events=[], local_change=lambda: client.patch(f"/events/{before.id}", json={"title": "Too late"})
    )

    assert response.status_code == 404
    assert rows(engine) == []


def test_a_sync_that_hangs_gets_a_503_not_a_hung_request(world, monkeypatch):
    client, engine = world
    before = add_event(engine)
    monkeypatch.setattr(events_module.settings, "calendar_write_wait_seconds", 0.1)

    with locks.account_lock(1):  # a sync stuck mid-fetch
        response = client.patch(f"/events/{before.id}", json={"title": "Dentist (moved)"})

    assert response.status_code == 503
    assert "syncing" in response.json()["detail"]
    assert [e.title for e in rows(engine)] == ["Dentist"]


def test_an_event_deleted_mid_sync_is_not_brought_back_by_it(world, monkeypatch):
    client, engine = world
    before = add_event(engine)

    response = during_a_sync(monkeypatch, server_events=[before], local_change=lambda: client.delete(f"/events/{before.id}"))

    assert response.status_code == 204
    assert rows(engine) == []
