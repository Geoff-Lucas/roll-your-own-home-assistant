import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.browser import cdp
from app.browser.controller import BrowserUnavailable
from app.db import get_session
from app.models import Recipe
from app.routers import browser as browser_module

STATE = {"running": True, "url": "https://example.com/r", "title": "R", "can_go_back": False, "can_go_forward": False}


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(browser_module.router)
    app.dependency_overrides[get_session] = override_get_session

    calls = {"shown": None, "hidden": 0, "navigated": None}
    controller = browser_module.controller

    async def state():
        return STATE

    async def show(x, y, width, height):
        calls["shown"] = (x, y, width, height)

    async def hide():
        calls["hidden"] += 1

    async def navigate(address):
        if address == "bad":
            raise ValueError("Only http and https addresses are supported")
        calls["navigated"] = address

    async def noop():
        return None

    monkeypatch.setattr(controller, "state", state)
    monkeypatch.setattr(controller, "show", show)
    monkeypatch.setattr(controller, "hide", hide)
    monkeypatch.setattr(controller, "navigate", navigate)
    for name in ("back", "forward", "reload"):
        monkeypatch.setattr(controller, name, noop)
    return TestClient(app), engine, calls, controller


def test_show_places_the_window_and_returns_state(setup):
    client, _, calls, _ = setup

    res = client.post("/browser/show", json={"x": 0, "y": 330, "width": 1440, "height": 1500})

    assert res.status_code == 200
    assert calls["shown"] == (0, 330, 1440, 1500)
    assert res.json()["url"] == "https://example.com/r"


@pytest.mark.parametrize(
    "rect",
    [
        {"x": -1, "y": 0, "width": 100, "height": 100},
        {"x": 0, "y": 0, "width": 0, "height": 100},
        {"x": 0, "y": 0, "width": 100, "height": -5},
        {"x": 0, "y": 0},
    ],
)
def test_show_rejects_nonsense_rectangles(setup, rect):
    client, _, calls, _ = setup

    assert client.post("/browser/show", json=rect).status_code == 422
    assert calls["shown"] is None


def test_hide(setup):
    client, _, calls, _ = setup

    assert client.post("/browser/hide").status_code == 204
    assert calls["hidden"] == 1


def test_navigate_passes_the_typed_address_through(setup):
    client, _, calls, _ = setup

    assert client.post("/browser/navigate", json={"address": "chicken soup"}).status_code == 200
    assert calls["navigated"] == "chicken soup"


def test_navigate_reports_a_bad_address_as_400(setup):
    client, _, _, _ = setup

    res = client.post("/browser/navigate", json={"address": "bad"})

    assert res.status_code == 400
    assert "http" in res.json()["detail"]


@pytest.mark.parametrize("action", ["back", "forward", "reload"])
def test_history_actions_return_state(setup, action):
    client, _, _, _ = setup

    assert client.post(f"/browser/{action}").json()["running"] is True


def test_unavailable_browser_is_503_with_a_reason(setup, monkeypatch):
    client, _, _, controller = setup

    async def unavailable():
        raise BrowserUnavailable("Browser control needs wmctrl, which isn't installed on this machine")

    monkeypatch.setattr(controller, "state", unavailable)

    res = client.get("/browser/state")

    assert res.status_code == 503
    assert "wmctrl" in res.json()["detail"]


def test_a_browser_that_stops_responding_is_502(setup, monkeypatch):
    client, _, _, controller = setup

    async def unresponsive():
        raise cdp.CDPError("timed out")

    monkeypatch.setattr(controller, "reload", unresponsive)

    assert client.post("/browser/reload").status_code == 502


# --- "Add to recipes" -------------------------------------------------------


def _current_url(monkeypatch, controller, url):
    async def current_url():
        return url

    monkeypatch.setattr(controller, "current_url", current_url)


def _fake_importer(monkeypatch, title="Crunchwrap"):
    seen = []

    def importer(url):
        seen.append(url)
        return Recipe(title=title, source_url=url)

    monkeypatch.setattr(browser_module, "import_recipe_from_url", importer)
    return seen


def test_import_current_page_sends_the_browsers_url_to_the_importer(setup, monkeypatch):
    client, engine, _, controller = setup
    _current_url(monkeypatch, controller, "https://example.com/crunchwrap")
    seen = _fake_importer(monkeypatch)

    res = client.post("/browser/import-current")

    assert res.status_code == 201
    assert res.json()["title"] == "Crunchwrap"
    assert seen == ["https://example.com/crunchwrap"]
    with Session(engine) as session:
        assert [r.source_url for r in session.exec(select(Recipe)).all()] == ["https://example.com/crunchwrap"]


def test_import_refuses_when_there_is_no_web_page_to_import(setup, monkeypatch):
    client, _, _, controller = setup
    seen = _fake_importer(monkeypatch)

    for url in (None, "", "chrome://newtab/", "about:blank"):
        _current_url(monkeypatch, controller, url)
        res = client.post("/browser/import-current")
        assert res.status_code == 400, url
        assert "recipe page" in res.json()["detail"]

    assert seen == []  # never scraped anything


def test_import_refuses_a_page_that_is_already_saved(setup, monkeypatch):
    client, engine, _, controller = setup
    _current_url(monkeypatch, controller, "https://example.com/crunchwrap")
    _fake_importer(monkeypatch)
    assert client.post("/browser/import-current").status_code == 201

    again = client.post("/browser/import-current")

    assert again.status_code == 409
    assert "already in your recipes" in again.json()["detail"]
    with Session(engine) as session:
        assert len(session.exec(select(Recipe)).all()) == 1


def test_import_reports_pages_that_are_not_recipes(setup, monkeypatch):
    client, engine, _, controller = setup
    _current_url(monkeypatch, controller, "https://example.com/not-a-recipe")

    def importer(url):
        raise RuntimeError("No recipe schema found")

    monkeypatch.setattr(browser_module, "import_recipe_from_url", importer)

    res = client.post("/browser/import-current")

    assert res.status_code == 422
    assert "Couldn't find a recipe" in res.json()["detail"]
    with Session(engine) as session:
        assert len(session.exec(select(Recipe)).all()) == 0
