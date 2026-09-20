import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.routers import recipes as recipes_module


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    test_app = FastAPI()
    test_app.include_router(recipes_module.router)
    test_app.dependency_overrides[get_session] = override_get_session

    return TestClient(test_app)


def test_create_recipe_structures_ingredients(setup):
    client = setup

    res = client.post(
        "/recipes",
        json={"title": "Pancakes", "ingredients": ["2 cups flour", "1 tsp salt"], "steps": ["Mix", "Cook"]},
    )

    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "Pancakes"
    assert len(body["ingredients"]) == 2
    assert body["ingredients"][0]["raw_text"] == "2 cups flour"
    assert body["ingredients"][0]["name"] == "flour"
    assert body["ingredients"][0]["quantity_text"] == "2 cups"


def test_update_recipe_reparses_ingredients_when_provided(setup):
    client = setup
    created = client.post("/recipes", json={"title": "Pancakes", "ingredients": ["1 cup milk"]}).json()

    res = client.patch(f"/recipes/{created['id']}", json={"ingredients": ["3 eggs"]})

    assert res.status_code == 200
    ingredients = res.json()["ingredients"]
    assert len(ingredients) == 1
    assert ingredients[0]["raw_text"] == "3 eggs"
    assert ingredients[0]["name"] == "eggs"


def test_update_recipe_leaves_ingredients_untouched_when_not_provided(setup):
    client = setup
    created = client.post("/recipes", json={"title": "Pancakes", "ingredients": ["1 cup milk"]}).json()

    res = client.patch(f"/recipes/{created['id']}", json={"title": "Fluffy Pancakes"})

    assert res.status_code == 200
    assert res.json()["title"] == "Fluffy Pancakes"
    assert res.json()["ingredients"][0]["raw_text"] == "1 cup milk"


def test_import_recipe_uses_importer_and_never_downloads_image(setup, monkeypatch):
    client = setup

    from app.models import Recipe

    def fake_import(url):
        return Recipe(title="Imported Recipe", source_url=url, source_image_url="https://example.com/x.jpg")

    monkeypatch.setattr(recipes_module, "import_recipe_from_url", fake_import)

    res = client.post("/recipes/import", json={"url": "https://example.com/recipe"})

    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "Imported Recipe"
    assert body["source_image_url"] == "https://example.com/x.jpg"
    assert body["image_path"] is None


def test_import_recipe_returns_422_on_scrape_failure(setup, monkeypatch):
    client = setup

    def failing_import(url):
        raise ValueError("unsupported site")

    monkeypatch.setattr(recipes_module, "import_recipe_from_url", failing_import)

    res = client.post("/recipes/import", json={"url": "https://example.com/unsupported"})

    assert res.status_code == 422


def test_favoriting_triggers_image_download_attempt(setup, monkeypatch):
    client = setup
    created = client.post("/recipes", json={"title": "Soup"}).json()

    calls = []
    monkeypatch.setattr(recipes_module, "ensure_recipe_image_downloaded", lambda recipe: calls.append(recipe.id))

    res = client.post(f"/recipes/{created['id']}/favorite", params={"person_name": "Geoff"})

    assert res.status_code == 204
    assert calls == [created["id"]]


def test_favoriting_twice_by_the_same_person_only_downloads_once(setup, monkeypatch):
    client = setup
    created = client.post("/recipes", json={"title": "Soup"}).json()

    calls = []
    monkeypatch.setattr(recipes_module, "ensure_recipe_image_downloaded", lambda recipe: calls.append(recipe.id))

    client.post(f"/recipes/{created['id']}/favorite", params={"person_name": "Geoff"})
    client.post(f"/recipes/{created['id']}/favorite", params={"person_name": "Geoff"})

    assert len(calls) == 1  # second call was a no-op (already favorited by Geoff)


def test_list_favorite_recipe_ids_scoped_per_person(setup, monkeypatch):
    client = setup
    monkeypatch.setattr(recipes_module, "ensure_recipe_image_downloaded", lambda recipe: None)

    soup = client.post("/recipes", json={"title": "Soup"}).json()
    salad = client.post("/recipes", json={"title": "Salad"}).json()

    client.post(f"/recipes/{soup['id']}/favorite", params={"person_name": "Geoff"})
    client.post(f"/recipes/{salad['id']}/favorite", params={"person_name": "Alex"})

    geoff_favorites = client.get("/recipes/favorites", params={"person_name": "Geoff"}).json()
    alex_favorites = client.get("/recipes/favorites", params={"person_name": "Alex"}).json()

    assert geoff_favorites == [soup["id"]]
    assert alex_favorites == [salad["id"]]
