import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.models import Location
from app.routers import locations as locations_module


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(locations_module.router)
    app.dependency_overrides[get_session] = override_get_session

    with Session(engine) as session:
        session.add(Location(name="Fairfax, VA", latitude=38.84622, longitude=-77.30637))
        session.commit()

    # These are wiring tests: the weather refetch and the geocoding API are
    # exercised elsewhere / need the network, so stub them and record calls.
    calls = {"switched": 0}

    async def fake_switch():
        calls["switched"] += 1

    monkeypatch.setattr(locations_module, "switch_weather_location", fake_switch)
    return TestClient(app), calls


def names(state):
    return [location["name"] for location in state["locations"]]


def id_of(client, name):
    return next(loc["id"] for loc in client.get("/locations").json()["locations"] if loc["name"] == name)


DENVER = {"name": "Denver, Colorado", "latitude": 39.74, "longitude": -104.99}


def test_lists_locations_with_the_current_one_flagged(setup):
    client, _ = setup

    state = client.get("/locations").json()

    assert names(state) == ["Fairfax, VA"]
    assert state["locations"][0]["is_current"] is True
    assert state["current_id"] == state["locations"][0]["id"]


def test_adding_a_location_selects_it_and_refreshes_the_weather(setup):
    client, calls = setup

    res = client.post("/locations", json=DENVER)

    assert res.status_code == 201
    state = res.json()
    assert names(state)[0] == "Denver, Colorado"
    assert state["locations"][0]["is_current"] is True
    assert calls["switched"] == 1


def test_adding_the_same_place_twice_does_not_duplicate_it(setup):
    client, _ = setup

    client.post("/locations", json=DENVER)
    state = client.post("/locations", json=DENVER).json()

    assert names(state).count("Denver, Colorado") == 1


def test_rejects_out_of_range_coordinates(setup):
    client, calls = setup

    res = client.post("/locations", json={"name": "Nowhere", "latitude": 123.0, "longitude": 0})

    assert res.status_code == 422
    assert calls["switched"] == 0


def test_selecting_a_saved_location_makes_it_current(setup):
    client, calls = setup
    client.post("/locations", json=DENVER)
    fairfax_id = id_of(client, "Fairfax, VA")

    state = client.post(f"/locations/{fairfax_id}/select").json()

    assert state["current_id"] == fairfax_id
    assert names(state)[0] == "Fairfax, VA"
    assert calls["switched"] == 2


def test_selecting_an_unknown_location_is_404(setup):
    client, calls = setup

    assert client.post("/locations/999/select").status_code == 404
    assert calls["switched"] == 0


def test_a_saved_location_can_be_removed(setup):
    client, _ = setup
    client.post("/locations", json=DENVER)

    assert client.delete(f"/locations/{id_of(client, 'Fairfax, VA')}").status_code == 204
    assert names(client.get("/locations").json()) == ["Denver, Colorado"]


def test_the_current_location_cannot_be_removed(setup):
    client, _ = setup
    current_id = client.get("/locations").json()["current_id"]

    assert client.delete(f"/locations/{current_id}").status_code == 400
    assert len(client.get("/locations").json()["locations"]) == 1


def test_removing_an_unknown_location_is_404(setup):
    client, _ = setup

    assert client.delete("/locations/999").status_code == 404


def test_search_returns_candidates(setup, monkeypatch):
    client, _ = setup

    async def fake_search(query):
        return [{"name": f"{query}, Virginia", "latitude": 1.0, "longitude": 2.0}]

    monkeypatch.setattr(locations_module.geocoding, "search_places", fake_search)

    assert client.get("/locations/search", params={"q": "Fairfax"}).json() == [
        {"name": "Fairfax, Virginia", "latitude": 1.0, "longitude": 2.0}
    ]


def test_search_reports_a_bad_gateway_when_the_geocoder_is_down(setup, monkeypatch):
    client, _ = setup

    async def broken(query):
        raise RuntimeError("network down")

    monkeypatch.setattr(locations_module.geocoding, "search_places", broken)

    assert client.get("/locations/search", params={"q": "Fairfax"}).status_code == 502


def test_search_requires_at_least_two_characters(setup):
    client, _ = setup

    assert client.get("/locations/search", params={"q": "a"}).status_code == 422
