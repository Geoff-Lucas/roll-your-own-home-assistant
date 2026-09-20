import pytest

from app import weather


def test_describe_weather_code_known_and_unknown():
    assert weather.describe_weather_code(0) == ("clear", "Clear sky")
    assert weather.describe_weather_code(61) == ("rain", "Slight rain")
    assert weather.describe_weather_code(12345) == ("unknown", "Unknown")


def test_to_widget_shape_maps_current_and_forecast():
    raw = {
        "current": {"temperature_2m": 72.5, "weather_code": 1},
        "daily": {
            "time": ["2026-07-15", "2026-07-16"],
            "temperature_2m_max": [80.0, 78.0],
            "temperature_2m_min": [65.0, 63.0],
            "weather_code": [1, 61],
        },
        "current_units": {"temperature_2m": "°F"},
    }

    shaped = weather._to_widget_shape(raw)

    assert shaped["current"] == {"temperature": 72.5, "icon": "partly-cloudy", "description": "Mainly clear"}
    assert shaped["unit"] == "°F"
    assert shaped["forecast"] == [
        {"date": "2026-07-15", "high": 80.0, "low": 65.0, "icon": "partly-cloudy", "description": "Mainly clear"},
        {"date": "2026-07-16", "high": 78.0, "low": 63.0, "icon": "rain", "description": "Slight rain"},
    ]


@pytest.mark.anyio
async def test_refresh_weather_cache_populates_cache(monkeypatch):
    async def fake_fetch():
        return {
            "current": {"temperature_2m": 55.0, "weather_code": 3},
            "daily": {
                "time": ["2026-07-15"],
                "temperature_2m_max": [60.0],
                "temperature_2m_min": [50.0],
                "weather_code": [3],
            },
            "current_units": {"temperature_2m": "°F"},
        }

    monkeypatch.setattr(weather, "_fetch_weather", fake_fetch)
    weather._cache["data"] = None

    await weather.refresh_weather_cache()

    cached = weather.get_cached_weather()
    assert cached["current"]["temperature"] == 55.0
    assert cached["current"]["icon"] == "cloudy"


@pytest.mark.anyio
async def test_refresh_weather_cache_keeps_last_value_on_failure(monkeypatch):
    async def failing_fetch():
        raise RuntimeError("network down")

    weather._cache["data"] = {"current": {"temperature": 70.0}}
    monkeypatch.setattr(weather, "_fetch_weather", failing_fetch)

    await weather.refresh_weather_cache()

    assert weather.get_cached_weather() == {"current": {"temperature": 70.0}}
