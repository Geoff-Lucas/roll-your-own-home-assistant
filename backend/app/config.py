from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HOME_ORGANIZER_", env_file=".env", extra="ignore")

    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    database_filename: str = "home_organizer.db"

    # Deliberately outside the repo by default — see PLAN.md "Security & credentials".
    encryption_key_path: Path = Path.home() / ".home_organizer" / "secret.key"

    cors_origins: list[str] = ["*"]

    # CalDAV sync worker (see app/sync/)
    sync_interval_seconds: int = 300
    sync_window_past_days: int = 30
    sync_window_future_days: int = 365

    # Weather (see app/weather.py). The location shown is chosen at runtime
    # from the on-screen picker (see app/locations.py); these three only seed
    # the very first entry when no location has ever been selected. Defaults
    # are a placeholder (New York City) — set HOME_ORGANIZER_WEATHER_LATITUDE/
    # LONGITUDE/LOCATION_NAME for the actual install location.
    weather_latitude: float = 40.7128
    weather_longitude: float = -74.0060
    weather_location_name: str = "Home"
    # Saved locations not selected for this long are deleted (never the current one).
    location_retention_days: int = 365
    weather_temperature_unit: str = "fahrenheit"  # or "celsius"
    weather_poll_interval_seconds: int = 1800

    # Timers, alarms and stopwatches (see app/timers/) and the audio they use.
    # audio_device is an ALSA device name for `aplay -D`; "default" follows the
    # system's default sink. IANA zone name for alarms; blank = the machine's own.
    audio_device: str = "default"
    timezone: str = ""
    timer_ring_repeat_seconds: float = 2.5  # gap between chimes while something is ringing
    timer_ring_max_seconds: int = 300  # stop chiming (but keep showing the alert) after this long

    # Voice assistant (see app/voice/). mic_device is an ALSA capture device for
    # `arecord -D`; name-based ("plughw:CARD=Microphone,DEV=0") survives the USB
    # card number changing between boots. Speech-to-text is local (faster-whisper)
    # and never downloads a model on its own — run `python -m app.voice.setup`.
    mic_device: str = "default"
    voice_stt_model: str = "base.en"
    voice_stt_auto_download: bool = False
    voice_tts: str = "auto"  # auto | piper | espeak | none
    # espeak-ng voice and speed (words per minute). Voices are language codes with
    # optional variants: "en-us", "en-gb", "en-us+f3" (a woman), "en-us+m3", "en-us+whisper".
    # List them with `espeak-ng --voices=en`; variants are in espeak-ng-data/voices/!v.
    voice_espeak_voice: str = "en-us"
    voice_espeak_speed: int = 160
    voice_piper_binary: str = ""  # path to the piper executable
    voice_piper_model: str = ""  # path to a piper voice (.onnx)
    voice_silence_seconds: float = 1.1  # quiet this long after speech = finished
    voice_start_timeout_seconds: float = 6.0  # give up if nothing is said
    voice_max_seconds: float = 15.0
    # Hands-free: say "Hey Jarvis" instead of tapping. Off by default because it
    # keeps the microphone open all the time (the audio is only ever compared
    # against the wake-word model and thrown away; nothing is recorded or
    # recognized until the phrase is heard).
    voice_wakeword_enabled: bool = False
    voice_wakeword_threshold: float = 0.5  # 0-1; lower = more sensitive, more false triggers
    voice_wakeword_cooldown_seconds: float = 2.0

    @property
    def voice_models_dir(self) -> Path:
        return self.data_dir / "voice" / "models"

    # Browser tab (see app/browser/) — a second, real Chromium window the
    # backend places under the app's header and steers over the DevTools
    # protocol. Only meaningful on the kiosk itself (needs a display, chromium,
    # xdotool and wmctrl); everywhere else the endpoints report 503.
    browser_command: str = "chromium"
    browser_display: str = ":0"
    browser_debug_port: int = 9222
    browser_home_url: str = "https://www.google.com/"

    @property
    def browser_profile_dir(self) -> Path:
        # Persistent so logins/cookies survive restarts (e.g. staying signed in
        # to a search or chat site). Contains cookies — keep it out of backups.
        return self.data_dir / "browser-profile"

    @property
    def database_path(self) -> Path:
        return self.data_dir / self.database_filename

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    @property
    def recipe_images_dir(self) -> Path:
        # Only ever populated lazily, on first favorite — see app/recipes/images.py.
        return self.data_dir / "recipe_images"

    # Ambient mode (see app/ambient/) — idle photo carousel, overnight dim
    # schedule, motion wake. Photos are never fetched by the app itself
    # (see PLAN.md "Ambient mode") — this dir is populated externally (NAS
    # rsync, Google Photos downloader script, etc.) and the app just reads it.
    ambient_idle_timeout_seconds: int = 300
    ambient_dim_start_hour: int = 22  # 10pm local time
    ambient_dim_end_hour: int = 7  # 7am local time
    ambient_motion_enabled: bool = True
    ambient_motion_gpio_pin: int = 4
    ambient_motion_active_window_seconds: int = 30  # how long "motion detected" stays true after the last trigger

    @property
    def ambient_photos_dir(self) -> Path:
        return self.data_dir / "ambient_photos"

    # Google CalDAV requires OAuth 2.0 exclusively as of mid-2023 — basic
    # auth (username + app password), which is what iCloud and generic
    # CalDAV accounts use, gets a flat 401. See app/sync/google_oauth.py.
    # Client ID/secret are application-level (one Google Cloud OAuth client
    # registration covers every linked Google account), not per-account.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/api/google-oauth/callback"

    @property
    def frontend_dist_dir(self) -> Path:
        # The Svelte frontend is built on the dev machine, never on the Pi
        # (see PLAN.md "Deployment & updates") — this just points at wherever
        # that build output was copied to. Doesn't exist in local dev (Vite's
        # own dev server + proxy is used instead — see frontend/vite.config.js),
        # only on a deployed Pi; main.py only mounts it if the directory exists.
        return Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


settings = Settings()
