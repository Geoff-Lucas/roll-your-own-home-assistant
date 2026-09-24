"""Typing a recipe in by hand: it has to come out just like an imported one,
so it can go on the meal plan and, later, feed a shopping list."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.recipes import importer
from app.routers import recipes as recipes_module


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(recipes_module.router)
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def create(client, **fields):
    return client.post("/recipes", json={"title": "Grandma's chili", **fields})


def test_ingredients_are_structured_for_a_shopping_list(client):
    body = create(client, ingredients=["2 cups flour", "1 lb ground beef"]).json()

    assert body["ingredients"][0] == {"raw_text": "2 cups flour", "name": "flour", "quantity_text": "2 cups"}
    assert body["ingredients"][1]["name"] == "ground beef"


def test_typed_and_imported_recipes_structure_ingredients_the_same_way():
    # Both go through the one parser, so a shopping list can treat them alike.
    assert importer.parse_ingredient_line is recipes_module.parse_ingredient_line


def test_blank_lines_are_dropped(client):
    body = create(client, ingredients=["2 eggs", "", "   ", "1 cup milk", ""], steps=["", "Whisk.", "  "]).json()

    assert [i["raw_text"] for i in body["ingredients"]] == ["2 eggs", "1 cup milk"]
    assert body["steps"] == ["Whisk."]


def test_bullets_typed_before_ingredients_are_dropped(client):
    body = create(client, ingredients=["- 2 eggs", "• 1 cup milk", "* salt"]).json()

    assert [i["raw_text"] for i in body["ingredients"]] == ["2 eggs", "1 cup milk", "salt"]


def test_quantities_that_look_like_numbering_are_kept(client):
    body = create(client, ingredients=["1.5 cups sugar", "2 tbsp butter"]).json()

    assert [i["raw_text"] for i in body["ingredients"]] == ["1.5 cups sugar", "2 tbsp butter"]


def test_step_numbers_are_dropped_since_steps_are_shown_numbered(client):
    body = create(client, steps=["1. Brown the beef.", "2) Add the beans.", "Step 3: Simmer.", "- Serve."]).json()

    assert body["steps"] == ["Brown the beef.", "Add the beans.", "Simmer.", "Serve."]


def test_tags_are_tidied(client):
    body = create(client, dietary_tags=[" vegetarian", "", "Vegetarian", "gluten-free "], allergens=["dairy", " "]).json()

    assert body["dietary_tags"] == ["vegetarian", "gluten-free"]
    assert body["allergens"] == ["dairy"]


@pytest.mark.parametrize(
    "fields",
    [
        {"title": ""},
        {"title": "   "},
        {"servings": 0},
        {"prep_time_minutes": -5},
        {"cook_time_minutes": -1},
    ],
)
def test_nonsense_is_refused(client, fields):
    assert create(client, **fields).status_code == 422


def test_the_title_is_trimmed(client):
    assert create(client, title="  Chili  ").json()["title"] == "Chili"


def test_editing_tidies_lines_the_same_way(client):
    recipe = create(client, ingredients=["2 eggs"]).json()

    body = client.patch(f"/recipes/{recipe['id']}", json={"ingredients": ["- 3 eggs", ""], "steps": ["1. Beat."]}).json()

    assert [i["raw_text"] for i in body["ingredients"]] == ["3 eggs"]
    assert body["ingredients"][0]["name"] == "eggs"
    assert body["steps"] == ["Beat."]


def test_editing_can_clear_a_number(client):
    recipe = create(client, servings=4).json()

    assert client.patch(f"/recipes/{recipe['id']}", json={"servings": None}).json()["servings"] is None


def test_a_typed_recipe_can_go_on_the_meal_plan(client):
    # Same router the meal planner uses to look recipes up.
    recipe = create(client, ingredients=["2 eggs"]).json()

    assert client.get("/recipes").json()[0]["id"] == recipe["id"]
