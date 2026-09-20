from fastapi import APIRouter, HTTPException

from ..weather import get_cached_weather

router = APIRouter(prefix="/weather", tags=["weather"])


@router.get("")
def get_weather() -> dict:
    data = get_cached_weather()
    if data is None:
        # Only happens in the brief window right at startup before the
        # first refresh completes, or if every attempt so far has failed.
        raise HTTPException(status_code=503, detail="Weather not available yet")
    return data
