from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.models import Recipe
from app.routers import meal_plan as meal_plan_module


@pytest.fixture
def setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(meal_plan_module.router)
    app.dependency_overrides[get_session] = override_get_session

    with Session(engine) as session:
        session.add(Recipe(id=1, title="Tacos"))
        session.commit()

    return TestClient(app)


def test_default_week_returns_seven_days_all_empty(setup):
    client = setup

    res = client.get("/meal-plan")

    assert res.status_code == 200
    body = res.json()
    assert len(body) == 7
    assert all(entry["recipe_id"] is None for entry in body)


def test_this_week_is_the_households_week(setup, monkeypatch):
    # The household's date (its timezone setting), not the machine clock's.
    monkeypatch.setattr(meal_plan_module, "local_today", lambda: date(2026, 9, 23))  # a Wednesday

    days = [entry["plan_date"] for entry in setup.get("/meal-plan").json()]

    assert days[0] == "2026-09-20" and days[-1] == "2026-09-26"  # Sunday to Saturday


def test_explicit_range_returns_matching_day_count(setup):
    client = setup
    start = date.today()
    end = start + timedelta(days=2)

    res = client.get("/meal-plan", params={"start": start.isoformat(), "end": end.isoformat()})

    assert res.status_code == 200
    assert len(res.json()) == 3


def test_set_meal_plan_assigns_a_recipe(setup):
    client = setup
    plan_date = date.today().isoformat()

    res = client.put(f"/meal-plan/{plan_date}", json={"recipe_id": 1})

    assert res.status_code == 200
    body = res.json()
    assert body["recipe_id"] == 1
    assert body["recipe_title"] == "Tacos"

    # shows up when refetching the week
    week = client.get("/meal-plan").json()
    matching = next(e for e in week if e["plan_date"] == plan_date)
    assert matching["recipe_id"] == 1


def test_set_meal_plan_can_clear_an_assignment(setup):
    client = setup
    plan_date = date.today().isoformat()
    client.put(f"/meal-plan/{plan_date}", json={"recipe_id": 1})

    res = client.put(f"/meal-plan/{plan_date}", json={"recipe_id": None})

    assert res.status_code == 200
    assert res.json()["recipe_id"] is None
