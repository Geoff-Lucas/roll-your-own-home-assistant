from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.routers import timers as timers_module
from app.timers import service


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(timers_module.router)
    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr(service.settings, "timezone", "America/New_York")
    return TestClient(app), engine


def make_ring(engine, timer_id):
    """Fast-forward: make a timer come due and ring."""
    with Session(engine) as session:
        service.tick(session, now=datetime(2100, 1, 1))


def ids(state):
    return [item["id"] for item in state["items"]]


def test_creating_a_timer_returns_it_with_its_countdown(setup):
    client, _ = setup

    res = client.post("/timers", json={"kind": "timer", "seconds": 600, "label": "pasta"})

    assert res.status_code == 201
    body = res.json()
    assert (body["kind"], body["state"], body["label"]) == ("timer", "running", "pasta")
    assert 598 <= body["remaining_seconds"] <= 600
    assert [item["id"] for item in body["items"]] == [body["id"]]


def test_creating_an_alarm_and_a_stopwatch(setup):
    client, _ = setup

    alarm = client.post("/timers", json={"kind": "alarm", "time": "07:30", "repeat": "weekdays"}).json()
    watch = client.post("/timers", json={"kind": "stopwatch"}).json()

    assert (alarm["alarm_time"], alarm["repeat"]) == ("07:30", "weekdays")
    assert alarm["remaining_seconds"] > 0
    assert watch["kind"] == "stopwatch" and watch["elapsed_seconds"] >= 0


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "timer"},  # no length
        {"kind": "timer", "seconds": 0},
        {"kind": "timer", "seconds": 10**7},
        {"kind": "alarm"},  # no time
        {"kind": "alarm", "time": "7:30"},
        {"kind": "alarm", "time": "25:00"},
        {"kind": "alarm", "time": "07:30", "repeat": "weekly"},
        {"kind": "microwave", "seconds": 5},
        {"kind": "timer", "seconds": 5, "label": "x" * 61},
    ],
)
def test_bad_creation_requests_are_rejected(setup, payload):
    client, _ = setup

    assert client.post("/timers", json=payload).status_code == 422
    assert client.get("/timers").json()["items"] == []


def test_pause_and_resume_a_timer(setup):
    client, _ = setup
    timer_id = client.post("/timers", json={"kind": "timer", "seconds": 600}).json()["id"]

    paused = client.post(f"/timers/{timer_id}/pause").json()["items"][0]
    assert paused["state"] == "paused"
    assert 598 <= paused["remaining_seconds"] <= 600

    resumed = client.post(f"/timers/{timer_id}/resume").json()["items"][0]
    assert resumed["state"] == "running"


def test_impossible_moves_are_a_409_not_a_crash(setup):
    client, _ = setup
    timer_id = client.post("/timers", json={"kind": "timer", "seconds": 600}).json()["id"]

    assert client.post(f"/timers/{timer_id}/resume").status_code == 409  # not paused
    assert client.post(f"/timers/{timer_id}/snooze", json={"minutes": 5}).status_code == 409  # not ringing
    assert client.post(f"/timers/{timer_id}/dismiss").status_code == 409  # not ringing
    assert client.post(f"/timers/{timer_id}/reset").status_code == 409  # not a stopwatch


def test_a_ringing_timer_can_be_snoozed_or_dismissed(setup):
    client, engine = setup
    first = client.post("/timers", json={"kind": "timer", "seconds": 1}).json()["id"]
    second = client.post("/timers", json={"kind": "timer", "seconds": 1}).json()["id"]
    make_ring(engine, first)

    items = {item["id"]: item for item in client.get("/timers").json()["items"]}
    assert items[first]["state"] == items[second]["state"] == "ringing"

    snoozed = client.post(f"/timers/{first}/snooze", json={"minutes": 10}).json()["items"]
    assert next(i for i in snoozed if i["id"] == first)["state"] == "running"

    after = client.post(f"/timers/{second}/dismiss").json()
    assert ids(after) == [first]  # dismissed timer is gone


def test_snooze_defaults_to_five_minutes_and_is_bounded(setup):
    client, engine = setup
    timer_id = client.post("/timers", json={"kind": "timer", "seconds": 1}).json()["id"]
    make_ring(engine, timer_id)

    assert client.post(f"/timers/{timer_id}/snooze", json={"minutes": 0}).status_code == 422
    assert client.post(f"/timers/{timer_id}/snooze", json={"minutes": 500}).status_code == 422
    snoozed = client.post(f"/timers/{timer_id}/snooze", json={}).json()["items"][0]
    assert 298 <= snoozed["remaining_seconds"] <= 300


def test_stopwatch_pause_resume_reset(setup):
    client, _ = setup
    watch_id = client.post("/timers", json={"kind": "stopwatch"}).json()["id"]

    assert client.post(f"/timers/{watch_id}/pause").json()["items"][0]["state"] == "paused"
    assert client.post(f"/timers/{watch_id}/resume").json()["items"][0]["state"] == "running"
    reset = client.post(f"/timers/{watch_id}/reset").json()["items"][0]
    assert (reset["state"], reset["elapsed_seconds"]) == ("paused", 0)


def test_delete_cancels_anything_in_any_state(setup):
    client, _ = setup
    timer_id = client.post("/timers", json={"kind": "timer", "seconds": 600}).json()["id"]
    alarm_id = client.post("/timers", json={"kind": "alarm", "time": "07:00", "repeat": "daily"}).json()["id"]

    assert client.delete(f"/timers/{timer_id}").status_code == 204
    assert client.delete(f"/timers/{alarm_id}").status_code == 204  # even a repeating alarm, for good
    assert client.get("/timers").json()["items"] == []


@pytest.mark.parametrize("path", ["pause", "resume", "reset", "dismiss"])
def test_unknown_ids_are_404(setup, path):
    client, _ = setup

    assert client.post(f"/timers/999/{path}").status_code == 404
    assert client.post("/timers/999/snooze", json={"minutes": 5}).status_code == 404
    assert client.delete("/timers/999").status_code == 404


def test_the_test_chime_endpoint_reports_whether_sound_played(setup, monkeypatch):
    client, _ = setup

    monkeypatch.setattr(timers_module, "play_chime", lambda: True)
    assert client.post("/timers/test-chime").status_code == 204

    monkeypatch.setattr(timers_module, "play_chime", lambda: False)
    assert client.post("/timers/test-chime").status_code == 503
