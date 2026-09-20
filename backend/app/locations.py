"""Saved weather locations: which one is current, seeding, and retention.

The current location is whichever row was selected most recently. Rows not
selected for `settings.location_retention_days` are purged, except the
current one — so a device left showing one place for years never loses it.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from .config import settings
from .models import Location
from .time_utils import to_naive_utc

# Two picker results within about half a kilometre are the same place —
# avoids saving "Fairfax" twice because the search returned it twice.
_SAME_PLACE_DEGREES = 0.005


def _now() -> datetime:
    return to_naive_utc(datetime.now(timezone.utc))


def list_locations(session: Session) -> list[Location]:
    """Most recently selected first (so the current one is first)."""
    return list(session.exec(select(Location).order_by(Location.last_selected_at.desc(), Location.id.desc())))


def get_current_location(session: Session) -> Optional[Location]:
    return session.exec(select(Location).order_by(Location.last_selected_at.desc(), Location.id.desc())).first()


def seed_default_location(session: Session) -> None:
    """First run only: create the initial entry from config so the widget has
    something to show before anyone has used the picker."""
    if get_current_location(session) is not None:
        return
    session.add(
        Location(
            name=settings.weather_location_name,
            latitude=settings.weather_latitude,
            longitude=settings.weather_longitude,
        )
    )
    session.commit()


def select_location(session: Session, location: Location) -> Location:
    location.last_selected_at = _now()
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


def add_or_select_location(session: Session, name: str, latitude: float, longitude: float) -> Location:
    for existing in list_locations(session):
        if (
            abs(existing.latitude - latitude) < _SAME_PLACE_DEGREES
            and abs(existing.longitude - longitude) < _SAME_PLACE_DEGREES
        ):
            return select_location(session, existing)
    return select_location(session, _create(session, name, latitude, longitude))


def _create(session: Session, name: str, latitude: float, longitude: float) -> Location:
    location = Location(name=name, latitude=latitude, longitude=longitude)
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


def purge_stale_locations(session: Session, now: Optional[datetime] = None) -> int:
    """Delete locations not selected within the retention window, sparing the
    current one. Returns how many were removed."""
    now = now or _now()
    cutoff = now - timedelta(days=settings.location_retention_days)
    current = get_current_location(session)
    stale = [
        location
        for location in session.exec(select(Location).where(Location.last_selected_at < cutoff))
        if current is None or location.id != current.id
    ]
    for location in stale:
        session.delete(location)
    session.commit()
    return len(stale)
