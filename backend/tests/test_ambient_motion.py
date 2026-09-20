from app import config
from app.ambient import motion


def test_no_motion_detected_initially():
    motion._last_motion_at = None
    assert motion.is_motion_recently_detected() is False


def test_motion_is_active_within_the_window_and_expires_after(monkeypatch):
    monkeypatch.setattr(config.settings, "ambient_motion_active_window_seconds", 30)

    fake_time = [1000.0]
    monkeypatch.setattr(motion.time, "monotonic", lambda: fake_time[0])

    motion._on_motion()
    assert motion.is_motion_recently_detected() is True

    fake_time[0] += 10
    assert motion.is_motion_recently_detected() is True

    fake_time[0] += 25  # 35s total, past the 30s window
    assert motion.is_motion_recently_detected() is False


def test_start_motion_sensor_does_not_raise_without_gpio_hardware():
    # This dev machine (and CI) has no GPIO backend available — start_motion_sensor
    # must degrade gracefully (log a warning) rather than crash the app on startup.
    # This is the actual condition confirmed by hand: instantiating gpiozero's
    # MotionSensor here raises BadPinFactory.
    motion.start_motion_sensor()
