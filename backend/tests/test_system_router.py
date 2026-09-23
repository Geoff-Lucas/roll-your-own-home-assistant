import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import system as system_module
from app.system import SystemControlError


@pytest.fixture
def setup():
    app = FastAPI()
    app.include_router(system_module.router)
    return TestClient(app)


def test_minimize_succeeds_with_no_content(setup, monkeypatch):
    monkeypatch.setattr(system_module, "minimize_to_desktop", lambda: None)

    res = setup.post("/system/minimize")

    assert res.status_code == 204


def test_minimize_reports_503_when_it_cant_run_here(setup, monkeypatch):
    def broken():
        raise SystemControlError("xdotool is not installed (see deploy/README.md)")

    monkeypatch.setattr(system_module, "minimize_to_desktop", broken)

    res = setup.post("/system/minimize")

    assert res.status_code == 503
    assert "xdotool" in res.json()["detail"]
