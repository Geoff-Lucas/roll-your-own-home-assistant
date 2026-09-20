from datetime import datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import locations
from app.config import settings
from app.models import Location

NOW = datetime(2026, 9, 20, 12, 0)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def add(session, name, lat, lon, days_ago):
    location = Location(name=name, latitude=lat, longitude=lon, last_selected_at=NOW - timedelta(days=days_ago))
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


def test_seed_creates_the_first_location_from_config(session, monkeypatch):
    monkeypatch.setattr(settings, "weather_location_name", "Fairfax, VA")
    monkeypatch.setattr(settings, "weather_latitude", 38.846)
    monkeypatch.setattr(settings, "weather_longitude", -77.306)

    locations.seed_default_location(session)

    current = locations.get_current_location(session)
    assert (current.name, current.latitude, current.longitude) == ("Fairfax, VA", 38.846, -77.306)


def test_seed_does_nothing_when_a_location_already_exists(session):
    add(session, "Existing", 1.0, 2.0, days_ago=3)

    locations.seed_default_location(session)

    assert [loc.name for loc in locations.list_locations(session)] == ["Existing"]


def test_current_location_is_the_most_recently_selected(session):
    add(session, "Old", 1.0, 1.0, days_ago=30)
    newest = add(session, "New", 2.0, 2.0, days_ago=1)
    add(session, "Older", 3.0, 3.0, days_ago=90)

    assert locations.get_current_location(session).id == newest.id
    assert [loc.name for loc in locations.list_locations(session)] == ["New", "Old", "Older"]


def test_selecting_an_older_location_makes_it_current(session):
    add(session, "Home", 1.0, 1.0, days_ago=1)
    away = add(session, "Away", 2.0, 2.0, days_ago=40)

    locations.select_location(session, away)

    assert locations.get_current_location(session).name == "Away"


def test_adding_the_same_place_reselects_instead_of_duplicating(session):
    home = add(session, "Fairfax, VA", 38.84622, -77.30637, days_ago=1)
    add(session, "Elsewhere", 10.0, 10.0, days_ago=0)  # currently selected

    # Same place, slightly different coordinates and label from a fresh search.
    again = locations.add_or_select_location(session, "Fairfax, Virginia", 38.8462, -77.3064)

    assert again.id == home.id
    assert len(locations.list_locations(session)) == 2
    assert locations.get_current_location(session).id == home.id


def test_adding_a_new_place_creates_and_selects_it(session):
    add(session, "Home", 38.0, -77.0, days_ago=1)

    created = locations.add_or_select_location(session, "Denver, Colorado", 39.74, -104.99)

    assert created.name == "Denver, Colorado"
    assert locations.get_current_location(session).id == created.id


def test_purge_removes_locations_unused_for_a_year(session):
    add(session, "Recent", 1.0, 1.0, days_ago=1)
    add(session, "Nearly a year", 2.0, 2.0, days_ago=364)
    stale = add(session, "Over a year", 3.0, 3.0, days_ago=366)

    removed = locations.purge_stale_locations(session, now=NOW)

    assert removed == 1
    assert stale.id not in [loc.id for loc in locations.list_locations(session)]
    assert {loc.name for loc in locations.list_locations(session)} == {"Recent", "Nearly a year"}


def test_purge_never_removes_the_current_location_even_if_stale(session):
    # A device left on one place for years must not lose it.
    only = add(session, "Left alone", 1.0, 1.0, days_ago=800)

    removed = locations.purge_stale_locations(session, now=NOW)

    assert removed == 0
    assert locations.get_current_location(session).id == only.id


def test_purge_honors_the_configured_retention(session, monkeypatch):
    monkeypatch.setattr(settings, "location_retention_days", 30)
    add(session, "Current", 1.0, 1.0, days_ago=1)
    add(session, "Forty days", 2.0, 2.0, days_ago=40)

    assert locations.purge_stale_locations(session, now=NOW) == 1
    assert [loc.name for loc in locations.list_locations(session)] == ["Current"]
