import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.models import Account
from app.routers import google_oauth as google_oauth_module


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(google_oauth_module.router)
    app.dependency_overrides[get_session] = override_get_session

    google_oauth_module._pending.clear()
    monkeypatch.setattr(
        google_oauth_module,
        "build_authorization_url",
        lambda state: (f"https://accounts.google.com/fake?state={state}", "fake-code-verifier"),
    )

    return TestClient(app, follow_redirects=False), engine


def test_start_redirects_to_google_and_stores_pending(setup):
    client, _ = setup

    res = client.get("/google-oauth/start", params={"person_name": "Geoff", "display_name": "Geoff Google"})

    assert res.status_code in (302, 307)
    assert res.headers["location"].startswith("https://accounts.google.com/fake?state=")
    assert len(google_oauth_module._pending) == 1


def test_callback_creates_account_and_clears_pending(setup, monkeypatch):
    client, engine = setup
    client.get("/google-oauth/start", params={"person_name": "Geoff", "display_name": "Geoff Google", "color": "#111111"})
    state = next(iter(google_oauth_module._pending))

    monkeypatch.setattr(google_oauth_module, "exchange_code", lambda code, code_verifier: ("a-refresh-token", "geoff@gmail.com"))

    res = client.get("/google-oauth/callback", params={"code": "fake-code", "state": state})

    assert res.status_code == 200
    assert "geoff@gmail.com" in res.text
    assert state not in google_oauth_module._pending

    with Session(engine) as session:
        account = session.exec(select(Account)).one()
        assert account.provider == "google"
        assert account.person_name == "Geoff"
        assert account.color == "#111111"
        assert account.username == "geoff@gmail.com"
        assert account.caldav_url == "https://apidata.googleusercontent.com/caldav/v2/geoff@gmail.com/user"
        assert account.oauth_refresh_token is not None
        assert account.encrypted_credential is None


def test_callback_with_unknown_state_returns_400(setup):
    client, _ = setup

    res = client.get("/google-oauth/callback", params={"code": "fake-code", "state": "never-issued"})

    assert res.status_code == 400


def test_callback_passes_the_verifier_from_start_through_to_exchange_code(setup, monkeypatch):
    # The exact bug hit against a real Google account: two independent Flow
    # instances (one per request) each mint their own code_verifier unless
    # the router explicitly carries it from /start to /callback.
    client, _ = setup
    client.get("/google-oauth/start", params={"person_name": "Geoff", "display_name": "Geoff Google"})
    state = next(iter(google_oauth_module._pending))

    captured = {}

    def fake_exchange_code(code, code_verifier):
        captured["code_verifier"] = code_verifier
        return "a-refresh-token", "geoff@gmail.com"

    monkeypatch.setattr(google_oauth_module, "exchange_code", fake_exchange_code)

    client.get("/google-oauth/callback", params={"code": "fake-code", "state": state})

    assert captured["code_verifier"] == "fake-code-verifier"
