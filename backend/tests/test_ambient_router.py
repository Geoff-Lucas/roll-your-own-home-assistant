from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.ambient import motion
from app.routers import ambient as ambient_module


def make_client():
    app = FastAPI()
    app.include_router(ambient_module.router)
    return TestClient(app)


def test_get_config_reflects_settings(monkeypatch):
    monkeypatch.setattr(config.settings, "ambient_idle_timeout_seconds", 123)
    monkeypatch.setattr(config.settings, "ambient_dim_start_hour", 21)
    monkeypatch.setattr(config.settings, "ambient_dim_end_hour", 6)

    res = make_client().get("/ambient/config")

    assert res.status_code == 200
    body = res.json()
    assert body["idle_timeout_seconds"] == 123
    assert body["dim_start_hour"] == 21
    assert body["dim_end_hour"] == 6


def test_get_photos_returns_url_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    photos_dir = config.settings.ambient_photos_dir
    photos_dir.mkdir(parents=True)
    (photos_dir / "sunset.jpg").write_bytes(b"fake")

    res = make_client().get("/ambient/photos")

    assert res.status_code == 200
    assert res.json() == ["/api/ambient-photos/sunset.jpg"]


def test_get_status_reports_motion(monkeypatch):
    monkeypatch.setattr(motion, "_last_motion_at", None)

    res = make_client().get("/ambient/status")

    assert res.status_code == 200
    assert res.json()["motion_detected"] is False
