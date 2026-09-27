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


# --- renewing an existing account's sign-in (Google expires it, e.g. after 7
# days while the Cloud project is in "Testing"), without making a duplicate ---


def add_linked_account(engine, email="geoff@gmail.com"):
    from app.models import Event
    from app.security.crypto import decrypt, encrypt

    with Session(engine) as session:
        account = Account(provider="google", display_name="Geoff Google", person_name="Geoff", username=email,
                          caldav_url=f"https://apidata.googleusercontent.com/caldav/v2/{email}/user",
                          oauth_refresh_token=encrypt("expired-token"))  # fmt: skip
        session.add(account)
        session.commit()
        session.add(Event(account_id=account.id, uid="kept", title="Dentist", all_day=True))
        session.commit()
        return account.id, decrypt


def relink(client, monkeypatch, account_id, email):
    res = client.get("/google-oauth/start", params={"account_id": account_id})
    assert res.status_code in (302, 307)
    state = next(iter(google_oauth_module._pending))
    monkeypatch.setattr(google_oauth_module, "exchange_code", lambda code, code_verifier: ("fresh-token", email))
    return client.get("/google-oauth/callback", params={"code": "fake-code", "state": state})


def test_relinking_renews_the_existing_account_instead_of_adding_one(setup, monkeypatch):
    from app.models import Event

    client, engine = setup
    account_id, decrypt = add_linked_account(engine)

    res = relink(client, monkeypatch, account_id, "geoff@gmail.com")

    assert res.status_code == 200 and "re-linked" in res.text
    with Session(engine) as session:
        (account,) = session.exec(select(Account)).all()  # still just the one
        assert account.id == account_id
        assert decrypt(account.oauth_refresh_token) == "fresh-token"
        assert [e.uid for e in session.exec(select(Event)).all()] == ["kept"]  # its events stay


def test_relinking_as_a_different_google_account_is_refused(setup, monkeypatch):
    client, engine = setup
    account_id, decrypt = add_linked_account(engine)

    res = relink(client, monkeypatch, account_id, "someone.else@gmail.com")

    assert res.status_code == 400
    assert "geoff@gmail.com" in res.json()["detail"]
    with Session(engine) as session:
        assert decrypt(session.get(Account, account_id).oauth_refresh_token) == "expired-token"


def test_relinking_an_account_that_does_not_exist_is_a_404(setup):
    client, _ = setup

    assert client.get("/google-oauth/start", params={"account_id": 99}).status_code == 404
    assert google_oauth_module._pending == {}


def test_a_new_link_still_needs_a_name(setup):
    client, _ = setup

    assert client.get("/google-oauth/start").status_code == 422
