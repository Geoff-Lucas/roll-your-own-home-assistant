from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.models import Account, Event
from app.routers import accounts as accounts_module
from app.sync import status, worker

T0 = datetime(2026, 9, 26, 22, 23, tzinfo=timezone.utc)


class RefreshError(Exception):
    """Named like google.auth's, which is what an expired Google sign-in raises."""


EXPIRED = RefreshError("invalid_grant: Token has been expired or revoked.")
OFFLINE = ConnectionError("Name or service not known")


def account(id_=1, provider="google"):
    return Account(id=id_, provider=provider, display_name="Geoff Google", person_name="Geoff")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(status, "_health", {})
    monkeypatch.setattr(status.settings, "sync_warning_after_minutes", 30)


def test_failures_are_told_apart():
    assert status.classify(EXPIRED) == "relink"
    assert status.classify(Exception("AuthorizationError at '/', 401 Unauthorized")) == "password"
    assert status.classify(OFFLINE) == "unreachable"


def test_an_expired_sign_in_is_shown_at_once_with_a_way_to_fix_it():
    status.record_failure(1, EXPIRED, now=T0)

    (problem,) = status.problems([account()], now=T0)

    assert problem["kind"] == "relink"
    assert problem["relink_url"] == "http://localhost:8000/api/google-oauth/start?account_id=1"


def test_a_brief_outage_is_not_shown():
    status.record_failure(1, OFFLINE, now=T0)
    status.record_failure(1, OFFLINE, now=T0 + timedelta(minutes=10))

    assert status.problems([account()], now=T0 + timedelta(minutes=29)) == []


def test_a_lasting_outage_is_shown_and_dated_from_its_first_failure():
    status.record_failure(1, OFFLINE, now=T0)
    status.record_failure(1, OFFLINE, now=T0 + timedelta(minutes=25))

    (problem,) = status.problems([account()], now=T0 + timedelta(minutes=31))

    assert problem["kind"] == "unreachable" and problem["relink_url"] is None
    assert problem["failing_since"] == T0.isoformat()


def test_a_successful_sync_clears_the_warning():
    status.record_failure(1, EXPIRED, now=T0)
    status.record_success(1, now=T0 + timedelta(minutes=5))

    assert status.problems([account()], now=T0 + timedelta(minutes=6)) == []


def test_the_last_update_survives_a_restart_by_coming_from_the_database():
    # After a restart this module has forgotten the last success; the events
    # table still knows when the server last confirmed them.
    status.record_failure(1, EXPIRED, now=T0 + timedelta(days=1))
    confirmed = T0 - timedelta(minutes=5)

    (problem,) = status.problems([account()], now=T0 + timedelta(days=1), last_synced={1: confirmed})

    assert problem["last_updated"] == confirmed.isoformat()


def test_the_newest_of_memory_and_database_wins():
    status.record_success(1, now=T0)
    status.record_failure(1, EXPIRED, now=T0 + timedelta(minutes=5))

    (problem,) = status.problems([account()], now=T0 + timedelta(minutes=6), last_synced={1: T0 - timedelta(days=2)})

    assert problem["last_updated"] == T0.isoformat()


def test_only_google_accounts_get_a_sign_in_link():
    status.record_failure(2, EXPIRED, now=T0)

    (problem,) = status.problems([account(2, provider="icloud")], now=T0)

    assert problem["relink_url"] is None


def test_the_sync_worker_records_what_happened(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=1, provider="google", display_name="Geoff Google", person_name="Geoff"))
        session.add(Account(id=2, provider="icloud", display_name="Work", person_name="Geoff"))
        session.commit()
    monkeypatch.setattr(worker, "engine", engine)

    def fetch(account, start, end):
        if account.id == 1:
            raise EXPIRED
        return []

    monkeypatch.setattr(worker, "fetch_account_ics", fetch)

    worker.sync_once()

    with Session(engine) as session:
        problems = status.problems([session.get(Account, 1), session.get(Account, 2)])
    assert [(p["account_id"], p["kind"]) for p in problems] == [(1, "relink")]  # the other synced fine


def test_the_api_lists_problems_and_forgets_a_removed_account():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=1, provider="google", display_name="Geoff Google", person_name="Geoff"))
        session.commit()
        for synced in (datetime(2026, 9, 26, 2, 18), datetime(2026, 9, 27, 2, 18)):  # naive UTC, as stored
            session.add(Event(account_id=1, uid=str(synced), title="x", all_day=True, last_synced_at=synced))
        session.commit()

    def override_get_session():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(accounts_module.router)
    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    status.record_failure(1, EXPIRED)

    (problem,) = client.get("/accounts/sync-problems").json()
    assert problem["display_name"] == "Geoff Google" and problem["kind"] == "relink"
    assert problem["last_updated"] == "2026-09-27T02:18:00+00:00"  # the newest confirmation, as UTC

    client.delete("/accounts/1")
    assert status._health == {}
