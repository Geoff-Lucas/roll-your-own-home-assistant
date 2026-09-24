import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from .ambient.motion import start_motion_sensor
from .browser.controller import controller as browser_controller
from .config import settings
from .db import engine, init_db
from .locations import seed_default_location
from .logging_setup import configure_logging
from .routers import (
    accounts,
    ambient,
    browser,
    events,
    google_oauth,
    health,
    locations,
    meal_plan,
    recipes,
    reminders,
    system,
    timers,
    voice,
    weather,
)
from .sync.worker import run_sync_loop
from .timers.alerts import run_timer_loop
from .voice.session import voice as voice_session
from .voice.tts import warm_up as warm_up_speech
from .voice.wakeword import OpenWakeWordDetector, WakeWordListener
from .weather import run_weather_loop

logger = logging.getLogger(__name__)


def build_wake_listener() -> Optional[WakeWordListener]:
    """The always-on "Hey Jarvis" listener, or None when it is switched off or
    can't run (the app carries on either way)."""
    if not settings.voice_wakeword_enabled:
        return None
    detector = OpenWakeWordDetector()
    ready, why = detector.status()
    if not ready:
        logger.warning("Wake word is enabled but unavailable: %s", why)
        return None
    listener = WakeWordListener(detector=detector, on_wake=lambda: voice_session.start(ack=True))
    voice_session.attach_wake(listener)
    return listener


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with Session(engine) as session:
        seed_default_location(session)
    start_motion_sensor()  # no-ops with a logged warning if there's no GPIO hardware
    background_tasks = [
        asyncio.create_task(run_sync_loop()),
        asyncio.create_task(run_weather_loop()),
        asyncio.create_task(run_timer_loop()),
        asyncio.create_task(warm_up_speech()),
    ]
    wake_listener = build_wake_listener()
    if wake_listener is not None:
        background_tasks.append(asyncio.create_task(wake_listener.run()))
    yield
    await browser_controller.shutdown()
    for task in background_tasks:
        task.cancel()
    for task in background_tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


# StaticFiles checks its directory exists at construction time, which
# happens at module import — before lifespan ever runs — so this has to be
# created here rather than in lifespan alongside init_db().
settings.recipe_images_dir.mkdir(parents=True, exist_ok=True)
settings.ambient_photos_dir.mkdir(parents=True, exist_ok=True)

configure_logging()

app = FastAPI(title="Home Organizer", lifespan=lifespan)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
if settings.cors_origins:  # none by default: see config.py
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Everything lives under /api so that, in production, the same FastAPI
# process can also serve the built frontend's static files from "/" without
# any path collisions (see frontend/README.md for the build/serve story).
app.include_router(health.router, prefix="/api")
app.include_router(accounts.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(recipes.router, prefix="/api")
app.include_router(weather.router, prefix="/api")
app.include_router(locations.router, prefix="/api")
app.include_router(browser.router, prefix="/api")
app.include_router(timers.router, prefix="/api")
app.include_router(voice.router, prefix="/api")
app.include_router(ambient.router, prefix="/api")
app.include_router(reminders.router, prefix="/api")
app.include_router(meal_plan.router, prefix="/api")
app.include_router(google_oauth.router, prefix="/api")
app.include_router(system.router, prefix="/api")

# Locally-downloaded recipe images (see app/recipes/images.py) — served
# directly rather than through a router since it's just static bytes.
app.mount("/api/recipe-images", StaticFiles(directory=settings.recipe_images_dir), name="recipe-images")

# Ambient carousel photos (see app/ambient/photos.py) — same story, static bytes.
app.mount("/api/ambient-photos", StaticFiles(directory=settings.ambient_photos_dir), name="ambient-photos")

# The built Svelte frontend (see deploy/README.md) — mounted at "/" last, so
# it only ever catches requests that didn't match one of the /api/* routes
# above. Doesn't exist in local dev (Vite's own dev server is used instead),
# so this is skipped entirely unless a build has actually been copied here.
if settings.frontend_dist_dir.is_dir():
    app.mount("/", StaticFiles(directory=settings.frontend_dist_dir, html=True), name="frontend")
