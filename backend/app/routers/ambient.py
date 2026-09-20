from datetime import datetime
from typing import List

from fastapi import APIRouter

from ..ambient.motion import is_motion_recently_detected
from ..ambient.photos import list_photo_filenames
from ..ambient.schedule import is_dim_time
from ..config import settings

router = APIRouter(prefix="/ambient", tags=["ambient"])


@router.get("/config")
def get_ambient_config() -> dict:
    return {
        "idle_timeout_seconds": settings.ambient_idle_timeout_seconds,
        "dim_start_hour": settings.ambient_dim_start_hour,
        "dim_end_hour": settings.ambient_dim_end_hour,
        "motion_enabled": settings.ambient_motion_enabled,
    }


@router.get("/photos", response_model=List[str])
def get_ambient_photos() -> List[str]:
    return [f"/api/ambient-photos/{name}" for name in list_photo_filenames()]


@router.get("/status")
def get_ambient_status() -> dict:
    return {
        "is_dim_time": is_dim_time(datetime.now(), settings.ambient_dim_start_hour, settings.ambient_dim_end_hour),
        "motion_detected": is_motion_recently_detected(),
    }
