"""Deleting something takes what belongs to it along, instead of leaving
orphaned rows behind (events of a removed account used to keep showing on the
calendar and in reminders)."""

from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.models import Account, Event, MealPlan, Recipe, RecipeFavorite
from app.routers import accounts, meal_plan, recipes

START = datetime(2026, 10, 1, 18, 0)


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'deletes.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def client(engine):
    def override_get_session():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    for router in (accounts.router, recipes.router, meal_plan.router):
        app.include_router(router)
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def add(engine, *rows):
    with Session(engine) as session:
        session.add_all(rows)
        session.commit()


def all_rows(engine, model):
    with Session(engine) as session:
        return session.exec(select(model)).all()


def event(account_id, uid):
    return Event(account_id=account_id, uid=uid, title=uid, start_time=START, end_time=START + timedelta(hours=1))


def test_deleting_an_account_removes_its_events_and_only_its_events(engine, client):
    add(engine, Account(id=1, provider="google", display_name="Mine", person_name="Geoff"),
        Account(id=2, provider="icloud", display_name="Theirs", person_name="Sam"))  # fmt: skip
    add(engine, event(1, "mine-a"), event(1, "mine-b"), event(2, "theirs"))

    assert client.delete("/accounts/1").status_code == 204

    assert [e.uid for e in all_rows(engine, Event)] == ["theirs"]


def test_deleting_a_recipe_removes_its_favorites(engine, client):
    add(engine, Recipe(id=1, title="Pancakes"), Recipe(id=2, title="Waffles"))
    add(engine, RecipeFavorite(recipe_id=1, person_name="Geoff"), RecipeFavorite(recipe_id=2, person_name="Geoff"))

    assert client.delete("/recipes/1").status_code == 204

    assert [f.recipe_id for f in all_rows(engine, RecipeFavorite)] == [2]


def test_deleting_a_recipe_unassigns_it_from_the_meal_plan_but_keeps_the_day(engine, client):
    add(engine, Recipe(id=1, title="Pancakes"))
    add(engine, MealPlan(plan_date=date(2026, 10, 1), recipe_id=1))

    assert client.delete("/recipes/1").status_code == 204

    (day,) = all_rows(engine, MealPlan)
    assert day.plan_date == date(2026, 10, 1) and day.recipe_id is None


def test_deleting_a_recipe_removes_its_downloaded_image(engine, client, tmp_path, monkeypatch):
    monkeypatch.setattr(recipes.settings, "data_dir", tmp_path)
    recipes.settings.recipe_images_dir.mkdir(parents=True)
    image = recipes.settings.recipe_images_dir / "1.jpg"
    image.write_bytes(b"jpeg")
    add(engine, Recipe(id=1, title="Pancakes", image_path="/api/recipe-images/1.jpg"))

    assert client.delete("/recipes/1").status_code == 204

    assert not image.exists()


def test_a_recipe_without_a_downloaded_image_deletes_fine(engine, client):
    add(engine, Recipe(id=1, title="Pancakes", source_image_url="https://example.com/p.jpg"))

    assert client.delete("/recipes/1").status_code == 204


def test_the_database_refuses_rows_that_point_at_nothing(engine):
    # SQLite ignores foreign keys unless each connection turns them on.
    with pytest.raises(IntegrityError):
        add(engine, event(99, "no-such-account"))
