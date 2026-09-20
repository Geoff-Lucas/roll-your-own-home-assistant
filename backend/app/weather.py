import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import httpx
from sqlmodel import Session

from .config import settings
from .db import engine
from .locations import get_current_location, purge_stale_locations

logger = logging.getLogger(__name__)

# WMO weather interpretation codes (used by Open-Meteo) -> (icon key, description).
# Not exhaustive, but covers what actually shows up in practice.
_WEATHER_CODES: Dict[int, Tuple[str, str]] = {
    0: ("clear", "Clear sky"),
    1: ("partly-cloudy", "Mainly clear"),
    2: ("partly-cloudy", "Partly cloudy"),
    3: ("cloudy", "Overcast"),
    45: ("fog", "Fog"),
    48: ("fog", "Depositing rime fog"),
    51: ("drizzle", "Light drizzle"),
    53: ("drizzle", "Moderate drizzle"),
    55: ("drizzle", "Dense drizzle"),
    56: ("drizzle", "Light freezing drizzle"),
    57: ("drizzle", "Dense freezing drizzle"),
    61: ("rain", "Slight rain"),
    63: ("rain", "Moderate rain"),
    65: ("rain", "Heavy rain"),
    66: ("rain", "Light freezing rain"),
    67: ("rain", "Heavy freezing rain"),
    71: ("snow", "Slight snow"),
    73: ("snow", "Moderate snow"),
    75: ("snow", "Heavy snow"),
    77: ("snow", "Snow grains"),
    80: ("rain", "Slight rain showers"),
    81: ("rain", "Moderate rain showers"),
    82: ("rain", "Violent rain showers"),
    85: ("snow", "Slight snow showers"),
    86: ("snow", "Heavy snow showers"),
    95: ("thunderstorm", "Thunderstorm"),
    96: ("thunderstorm", "Thunderstorm with slight hail"),
    99: ("thunderstorm", "Thunderstorm with heavy hail"),
}


def describe_weather_code(code: int) -> Tuple[str, str]:
    return _WEATHER_CODES.get(code, ("unknown", "Unknown"))


# In-memory only — weather is ephemeral, time-sensitive data with no value
# in surviving a restart; refresh_weather_cache runs once at startup anyway
# (see run_weather_loop), so the cache is warm again within seconds.
_cache: Dict[str, Optional[object]] = {"data": None, "fetched_at": None}


def _current_coordinates() -> Tuple[float, float]:
    """Where to fetch weather for: the location most recently picked on
    screen. Falls back to the configured seed values if the table is empty
    (e.g. a request racing the very first startup)."""
    with Session(engine) as session:
        location = get_current_location(session)
    if location is not None:
        return location.latitude, location.longitude
    return settings.weather_latitude, settings.weather_longitude


async def _fetch_weather() -> dict:
    latitude, longitude = _current_coordinates()
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
        "hourly": "temperature_2m,weather_code,precipitation_probability",
        "temperature_unit": settings.weather_temperature_unit,
        "timezone": "auto",
        "forecast_days": 5,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
        response.raise_for_status()
        return response.json()


# How many upcoming hours to hand the frontend. Much more than it displays on
# purpose: the backend only refreshes every 30 min, so the frontend picks the
# hours that are still "next" relative to the current time itself.
_HOURLY_LOOKAHEAD = 24


def _upcoming_hours(raw: dict) -> list:
    hourly = raw.get("hourly")
    if not hourly:
        return []
    # Open-Meteo returns times as naive local-to-the-location ISO strings
    # (we ask for timezone=auto), e.g. "2026-09-20T10:00" — same format as
    # current.time, so plain string comparison orders them correctly.
    now = raw["current"].get("time", "")
    rain_chance = hourly.get("precipitation_probability") or []
    hours = []
    for i, time in enumerate(hourly["time"]):
        if time <= now:
            continue
        icon, _ = describe_weather_code(hourly["weather_code"][i])
        hours.append(
            {
                "time": time,
                "temperature": hourly["temperature_2m"][i],
                "icon": icon,
                "precipitation_probability": rain_chance[i] if i < len(rain_chance) else None,
            }
        )
        if len(hours) == _HOURLY_LOOKAHEAD:
            break
    return hours


def _to_widget_shape(raw: dict) -> dict:
    current_icon, current_description = describe_weather_code(raw["current"]["weather_code"])
    daily = raw["daily"]
    forecast = []
    for i, date in enumerate(daily["time"]):
        icon, description = describe_weather_code(daily["weather_code"][i])
        forecast.append(
            {
                "date": date,
                "high": daily["temperature_2m_max"][i],
                "low": daily["temperature_2m_min"][i],
                "icon": icon,
                "description": description,
            }
        )
    return {
        "current": {
            "temperature": raw["current"]["temperature_2m"],
            "icon": current_icon,
            "description": current_description,
        },
        "forecast": forecast,
        "hourly": _upcoming_hours(raw),
        # Hourly times are local to the forecast location, which is no longer
        # necessarily where this device is — the frontend needs the offset
        # to know which of them are still in the future.
        "utc_offset_seconds": raw.get("utc_offset_seconds", 0),
        "unit": raw["current_units"]["temperature_2m"],
    }


async def refresh_weather_cache() -> None:
    try:
        raw = await _fetch_weather()
        _cache["data"] = _to_widget_shape(raw)
        _cache["fetched_at"] = datetime.now(timezone.utc)
    except Exception:
        # Same tolerance principle as the CalDAV sync worker: a failed
        # refresh keeps serving the last good value rather than blanking
        # the widget or crashing anything.
        logger.exception("Weather refresh failed — keeping last cached value")


def get_cached_weather() -> Optional[dict]:
    return _cache["data"]


async def switch_location() -> None:
    """Called right after a different location is picked. The cache is
    cleared first so a failed fetch can never leave the *previous* place's
    weather on screen under the new place's name — better to show "weather
    unavailable" until the (fast) retry succeeds."""
    _cache["data"] = None
    await refresh_weather_cache()


# After a failed fetch there is nothing cached to fall back on (startup, or
# just after switching location), so retry soon instead of waiting out a full
# 30-minute cycle.
_RETRY_WHEN_EMPTY_SECONDS = 60


def _purge_stale_locations() -> None:
    try:
        with Session(engine) as session:
            removed = purge_stale_locations(session)
        if removed:
            logger.info("Removed %d saved location(s) not selected within the retention window", removed)
    except Exception:
        logger.exception("Purging stale locations failed")


async def run_weather_loop() -> None:
    while True:
        await refresh_weather_cache()
        _purge_stale_locations()
        await asyncio.sleep(
            settings.weather_poll_interval_seconds if _cache["data"] is not None else _RETRY_WHEN_EMPTY_SECONDS
        )
