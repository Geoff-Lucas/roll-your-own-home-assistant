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


def _raw_with_hourly(now="2026-09-20T09:15", **hourly_overrides):
    hourly = {
        "time": ["2026-09-20T08:00", "2026-09-20T09:00", "2026-09-20T10:00", "2026-09-20T11:00"],
        "temperature_2m": [60.0, 62.0, 65.0, 68.0],
        "weather_code": [0, 1, 3, 61],
        "precipitation_probability": [0, 5, 20, 70],
    }
    hourly.update(hourly_overrides)
    return {
        "current": {"time": now, "temperature_2m": 62.0, "weather_code": 1},
        "daily": {
            "time": ["2026-09-20"],
            "temperature_2m_max": [70.0],
            "temperature_2m_min": [55.0],
            "weather_code": [1],
        },
        "hourly": hourly,
        "current_units": {"temperature_2m": "°F"},
    }


def test_hourly_only_includes_hours_after_now():
    shaped = weather._to_widget_shape(_raw_with_hourly(now="2026-09-20T09:15"))

    assert [h["time"] for h in shaped["hourly"]] == ["2026-09-20T10:00", "2026-09-20T11:00"]
    assert shaped["hourly"][0] == {
        "time": "2026-09-20T10:00",
        "temperature": 65.0,
        "icon": "cloudy",
        "precipitation_probability": 20,
    }
    assert shaped["hourly"][1]["icon"] == "rain"


def test_hourly_excludes_the_current_hour_boundary():
    # An hour that has exactly started is "now", not "upcoming".
    shaped = weather._to_widget_shape(_raw_with_hourly(now="2026-09-20T10:00"))

    assert [h["time"] for h in shaped["hourly"]] == ["2026-09-20T11:00"]


def test_hourly_is_capped_at_the_lookahead_limit():
    times = [f"2026-09-21T{h:02d}:00" for h in range(24)] + [f"2026-09-22T{h:02d}:00" for h in range(24)]
    raw = _raw_with_hourly(
        now="2026-09-20T09:15",
        time=times,
        temperature_2m=[50.0] * 48,
        weather_code=[0] * 48,
        precipitation_probability=[0] * 48,
    )

    shaped = weather._to_widget_shape(raw)

    assert len(shaped["hourly"]) == weather._HOURLY_LOOKAHEAD


def test_hourly_tolerates_missing_precipitation_data():
    raw = _raw_with_hourly(precipitation_probability=None)

    shaped = weather._to_widget_shape(raw)

    assert all(h["precipitation_probability"] is None for h in shaped["hourly"])


def test_shape_carries_the_utc_offset_for_non_local_locations():
    raw = _raw_with_hourly()
    raw["utc_offset_seconds"] = -25200  # e.g. Denver in summer

    assert weather._to_widget_shape(raw)["utc_offset_seconds"] == -25200


def test_shape_defaults_the_utc_offset_when_absent():
    assert weather._to_widget_shape(_raw_with_hourly())["utc_offset_seconds"] == 0


@pytest.mark.anyio
async def test_switch_location_never_leaves_the_previous_places_weather_behind(monkeypatch):
    # If the fetch for the newly selected place fails, the cache must be empty
    # (widget shows "unavailable"), not still holding the old place's weather
    # under the new place's name.
    async def failing_fetch():
        raise RuntimeError("network down")

    weather._cache["data"] = {"current": {"temperature": 70.0}}
    monkeypatch.setattr(weather, "_fetch_weather", failing_fetch)

    await weather.switch_location()

    assert weather.get_cached_weather() is None


@pytest.mark.anyio
async def test_switch_location_populates_fresh_weather_on_success(monkeypatch):
    async def fake_fetch():
        return _raw_with_hourly()

    weather._cache["data"] = {"current": {"temperature": 70.0}}
    monkeypatch.setattr(weather, "_fetch_weather", fake_fetch)

    await weather.switch_location()

    assert weather.get_cached_weather()["current"]["temperature"] == 62.0


def test_current_coordinates_follow_the_selected_location(monkeypatch):
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine

    from app.models import Location

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Location(name="Denver", latitude=39.74, longitude=-104.99))
        session.commit()
    monkeypatch.setattr(weather, "engine", engine)

    assert weather._current_coordinates() == (39.74, -104.99)


def test_current_coordinates_fall_back_to_config_when_no_location_exists(monkeypatch):
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel, create_engine

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(weather, "engine", engine)
    monkeypatch.setattr(weather.settings, "weather_latitude", 1.5)
    monkeypatch.setattr(weather.settings, "weather_longitude", 2.5)

    assert weather._current_coordinates() == (1.5, 2.5)


def test_shape_without_hourly_data_still_works():
    # Older cached/mocked responses have no "hourly" key at all.
    raw = _raw_with_hourly()
    del raw["hourly"]

    assert weather._to_widget_shape(raw)["hourly"] == []


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
