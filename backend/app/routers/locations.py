import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import geocoding
from ..db import SessionDep
from ..locations import (
    add_or_select_location,
    get_current_location,
    list_locations,
    select_location,
)
from ..models import Location
from ..weather import switch_location as switch_weather_location

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/locations", tags=["locations"])


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


def _state(session) -> dict:
    current = get_current_location(session)
    return {
        "current_id": current.id if current else None,
        "locations": [
            {
                "id": location.id,
                "name": location.name,
                "latitude": location.latitude,
                "longitude": location.longitude,
                "last_selected_at": location.last_selected_at,
                "is_current": current is not None and location.id == current.id,
            }
            for location in list_locations(session)
        ],
    }


@router.get("")
def get_locations(session: SessionDep) -> dict:
    return _state(session)


@router.get("/search")
async def search_locations(q: str = Query(min_length=2, max_length=100)) -> list[dict]:
    try:
        return await geocoding.search_places(q)
    except Exception as exc:
        logger.exception("Location search failed")
        raise HTTPException(status_code=502, detail="Location search is unavailable right now") from exc


@router.post("", status_code=201)
async def add_location(payload: LocationCreate, session: SessionDep) -> dict:
    add_or_select_location(session, payload.name.strip(), payload.latitude, payload.longitude)
    await switch_weather_location()
    return _state(session)


@router.post("/{location_id}/select")
async def select_saved_location(location_id: int, session: SessionDep) -> dict:
    location = session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    select_location(session, location)
    await switch_weather_location()
    return _state(session)


@router.delete("/{location_id}", status_code=204)
def delete_location(location_id: int, session: SessionDep) -> None:
    location = session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    current = get_current_location(session)
    if current is not None and current.id == location.id:
        raise HTTPException(status_code=400, detail="Can't remove the location currently being shown")
    session.delete(location)
    session.commit()
