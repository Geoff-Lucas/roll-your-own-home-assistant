import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import httpx

from .config import settings

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


async def _fetch_weather() -> dict:
    params = {
        "latitude": settings.weather_latitude,
        "longitude": settings.weather_longitude,
        "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
        "temperature_unit": settings.weather_temperature_unit,
        "timezone": "auto",
        "forecast_days": 5,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
        response.raise_for_status()
        return response.json()


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


async def run_weather_loop() -> None:
    while True:
        await refresh_weather_cache()
        await asyncio.sleep(settings.weather_poll_interval_seconds)
