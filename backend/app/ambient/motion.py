import logging
import threading
import time
import warnings
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)

_last_motion_at: Optional[float] = None
_lock = threading.Lock()


def _on_motion() -> None:
    global _last_motion_at
    with _lock:
        _last_motion_at = time.monotonic()


def is_motion_recently_detected() -> bool:
    with _lock:
        last = _last_motion_at
    if last is None:
        return False
    return (time.monotonic() - last) <= settings.ambient_motion_active_window_seconds


def start_motion_sensor() -> None:
    """Start listening on the configured GPIO pin for PIR motion events.

    Best-effort: this only does anything on a Raspberry Pi with a PIR
    sensor actually wired up. On any other platform — including every
    machine this project has been developed on so far — gpiozero has no
    GPIO backend to attach to and raises BadPinFactory. That's expected,
    not a bug: this logs a warning and no-ops rather than crashing the app.
    Motion-wake just isn't available in that case; touch-wake (frontend
    idle timer) still works on its own regardless.
    """
    if not settings.ambient_motion_enabled:
        return
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # gpiozero's own PinFactoryFallback spam — we log our own message instead
            from gpiozero import MotionSensor

            sensor = MotionSensor(settings.ambient_motion_gpio_pin)
        sensor.when_motion = _on_motion
    except Exception:
        logger.warning(
            "Motion sensor unavailable (no GPIO hardware, or gpiozero has nothing to attach to on this "
            "platform) — ambient mode will only wake on touch, not motion.",
            exc_info=True,
        )
