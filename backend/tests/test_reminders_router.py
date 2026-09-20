from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.models import Event
from app.routers import reminders as reminders_module

TODAY = date.today()


@pytest.fixture
def setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(reminders_module.router)
    app.dependency_overrides[get_session] = override_get_session

    return TestClient(app), engine


def seed_event(engine, **overrides) -> int:
    defaults = dict(account_id=1, uid="e1", title="Event", all_day=True)
    defaults.update(overrides)
    with Session(engine) as session:
        event = Event(**defaults)
        session.add(event)
        session.commit()
        session.refresh(event)
        return event.id


def test_upcoming_birthday_within_lead_time_is_surfaced(setup):
    client, engine = setup
    event_date = TODAY + timedelta(days=3)
    seed_event(engine, title="Sarah's Birthday", start_date=event_date, end_date=event_date + timedelta(days=1))

    res = client.get("/reminders")

    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["title"] == "Sarah's Birthday"
    assert body[0]["days_until"] == 3
    assert body[0]["text"] == "Get a card or gift"


def test_event_further_out_than_lead_days_is_not_surfaced(setup):
    client, engine = setup
    event_date = TODAY + timedelta(days=10)  # birthday lead time is 7 days
    seed_event(engine, title="Someone's Birthday", start_date=event_date, end_date=event_date + timedelta(days=1))

    assert client.get("/reminders").json() == []


def test_past_event_is_not_surfaced(setup):
    client, engine = setup
    event_date = TODAY - timedelta(days=1)
    seed_event(engine, title="Old Birthday", start_date=event_date, end_date=event_date + timedelta(days=1))

    assert client.get("/reminders").json() == []


def test_event_with_no_matching_keyword_and_no_manual_flag_is_not_surfaced(setup):
    client, engine = setup
    event_date = TODAY + timedelta(days=1)
    seed_event(engine, title="Dentist appointment", start_date=event_date, end_date=event_date + timedelta(days=1))

    assert client.get("/reminders").json() == []


def test_manual_reminder_flag_surfaces_regardless_of_title(setup):
    client, engine = setup
    event_date = TODAY + timedelta(days=2)
    seed_event(
        engine,
        title="Random meeting",
        start_date=event_date,
        end_date=event_date + timedelta(days=1),
        reminder_lead_days=5,
        reminder_text="Prepare slides",
    )

    body = client.get("/reminders").json()
    assert len(body) == 1
    assert body[0]["text"] == "Prepare slides"


def test_dismiss_removes_it_from_the_list(setup):
    client, engine = setup
    event_date = TODAY + timedelta(days=3)
    event_id = seed_event(engine, title="Sarah's Birthday", start_date=event_date, end_date=event_date + timedelta(days=1))

    assert len(client.get("/reminders").json()) == 1

    res = client.post(f"/reminders/{event_id}/dismiss")
    assert res.status_code == 204

    assert client.get("/reminders").json() == []


def test_dismiss_unknown_event_returns_404(setup):
    client, _ = setup
    assert client.post("/reminders/999/dismiss").status_code == 404
