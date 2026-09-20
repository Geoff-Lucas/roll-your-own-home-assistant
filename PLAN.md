# Home Organizer — Design Plan

## Constraints

- **Target hardware changed (Sept 2026):** now runs on an x86_64 mini PC (Ryzen 5 3500U, 16GB RAM, 512GB NVMe; hostname `h-asst`) running Debian 12 + XFCE, replacing the original Raspberry Pi 4B 4GB plan (judged too underpowered). Much of the document below was written against the Pi's constraints and still reads that way — the lightweight-stack choices remain fine, just no longer strictly forced. Pi-specific items are flagged in Hardware. See `deploy/README.md` for current provisioning steps.
- Display: 27" 2K touchscreen, portrait-mounted, always on during the day.
- Household use: multiple people, multiple calendar accounts.
- Touch is the primary input; on-screen keyboard needed.
- Voice assistant is cloud-assisted (not fully offline) — internet access is assumed available.
- Single device for MVP (no remote/phone access), but backend should stay API-first so that's not foreclosed later. There's now a stated future goal of an Android companion app (recipe browsing/upload, weekly shopping list) — the API-first design already accommodates it; revisit the LAN-only network assumption (see Security & credentials) when that's actually built, not before.

## Architecture

- **Backend:** Python, FastAPI. Async matters here — calendar sync polling, voice audio streaming, and WebSocket push to the frontend all benefit from it. Flask's sync-first model would fight this.
- **Frontend:** Svelte (not React, not Electron), served locally, displayed via Chromium in kiosk mode.
  - Electron is ruled out: a full Chromium + Node runtime per app is too heavy alongside a backend and voice pipeline on 4GB.
  - Native Python GUI (Kivy/PyQt) ruled out: worse visual results for more effort than modern CSS/web tooling.
  - Svelte compiles away its framework at build time (no virtual DOM runtime tax) — meaningful when RAM/CPU is shared with a browser process.
  - Performance rules: virtualize long lists (recipes, events), lazy-load images, animate only `transform`/`opacity` (GPU-composited), keep the always-on dashboard DOM shallow.
- **Storage:** SQLite as local source of truth / cache, on a USB3 SSD — not the SD card (see Hardware).

## Hardware

> **Pi-specific bullets below no longer apply to the mini PC:** the SSD/SD-card-wear point (it has an internal NVMe), the fan/`vcgencmd` temperature polling (would need `lm-sensors`/`/sys/class/thermal` instead, if wanted), the GPIO PIR sensor (no GPIO header — motion wake would need a USB presence sensor or camera-based approach; until then `app/ambient/motion.py` falls back gracefully to "no sensor"), and the missing-RTC concern (PCs have a battery-backed clock). The audio-hardware and network bullets still apply.

- **SSD:** USB3, **128GB minimum recommended** (32GB is technically workable but leaves no room for the photo carousel library, logs, and local backup staging — the cost difference to 128GB is a few dollars, not worth optimizing against). Move OS + app + DB here; SD card wears out fast under 24/7 write patterns (sync, logs, voice).
- **Cooling:** fan/heatsink case required — Chromium kiosk + backend + on-demand voice processing running for hours will throttle a passively-cooled Pi 4.
  - Don't rely on manually remembering to check the fan. Have the backend poll `vcgencmd measure_temp` periodically and log/flag when temp climbs above a threshold under normal load — a failing fan then surfaces as a diagnostic alert instead of a mysteriously sluggish/crashing device.
- **Motion sensor (for wake-from-ambient):** a PIR sensor (e.g. HC-SR501) on GPIO is the simple, cheap option — read via `gpiozero`, sets an "activity" flag the frontend/backend uses to exit ambient mode. An mmWave presence sensor is a worthwhile upgrade if false triggers or "went back to sleep while someone was still standing there reading a recipe" become annoying — mmWave detects presence, not just motion, so it doesn't drop out when someone's holding still. Start with PIR; it's cheap enough to swap later without redesigning anything.
- **Audio hardware (for voice):** neither the Pi nor a typical monitor provides a usable microphone, and wake-word detection across a room needs far-field pickup. Budget for a USB conference speakerphone (mic array + speaker in one, e.g. Anker PowerConf class) — it solves both voice input and TTS output in one device and needs no drivers. Required before build step 9 (voice pipeline).
- **Clock (RTC/NTP):** the Pi has no battery-backed clock — it gets time from NTP after boot. A calendar device showing the wrong time is worse than one showing nothing; either add a cheap I²C RTC module or have the app hold a "waiting for time sync" state until NTP has settled after boot.
- **Network:** prefer ethernet to the mount location if at all feasible; if WiFi, verify signal strength at the actual mount point (against the wall, behind a monitor) before committing.

## Calendar

- View layer: FullCalendar.io (vanilla JS, framework-agnostic, touch-capable, drag/resize built in) — don't build calendar UI from scratch.
- Sync: **one CalDAV integration, not two protocols** — but as of mid-2023, Google's CalDAV requires OAuth 2.0 exclusively (basic auth gets a flat 401; this was assumed to work the same as iCloud when originally written here, and didn't — confirmed against Google's own developer docs when actually testing against a real account). iCloud and any generic CalDAV provider (Fastmail, Nextcloud) still use simple app-specific-password basic auth. So: one CalDAV *transport* (`caldav_client.py`), but two auth paths feeding it — `security/crypto.py`-encrypted password for basic auth, OAuth refresh token (`app/sync/google_oauth.py`) for Google specifically. Account linking for Google is a browser-redirect flow (`GET /api/google-oauth/start` → Google login/consent → `/callback`), not a password entry field — requires a Google Cloud OAuth client ID/secret (`.env.example` has the setup steps).
  - Skip Google's native REST API initially — it only buys push-webhooks and finer free/busy queries, not needed yet. Revisit only if polling-based sync feels laggy.
  - **Write-back (build step 4) is now genuinely verified against a real Google account** — not just mocked tests. Two real bugs only showed up this way: (1) a locally created/edited event needs its `recurrence_id` set to match its own instant up front, or the next sync cycle fails to recognize it as the same row and silently swaps it out under a new id (fixed in `routers/events.py`, `_compute_recurrence_id`). (2) `caldav`'s built-in `get_event_by_uid()` is unusable against Google two ways: it crashes with `OSError: [Errno 22] Invalid argument` on Windows dev machines (an unbounded search falls back to expanding recurrences from year 1, and Windows' datetime can't `.astimezone()` that far back — Linux likely doesn't hit this, but nothing here should depend on that), and — the real finding — Google's CalDAV server doesn't honor server-side UID filtering at all, returning every event in range regardless of the `uid=` filter. Fixed by reusing the same bounded `search()` the read-sync already uses and matching UID client-side (`caldav_client._find_calendar_object`).
  - **Enabling Google Calendar linking requires two separate opt-ins** in Google Cloud Console, easy to miss: enabling the **Calendar API** is not the same as enabling the **CalDAV API** — both are required, and CalDAV specifically threw `accessNotConfigured` until enabled separately.
- Data model: accounts are first-class (`account_id`, provider, credentials, assigned color, display name) — one row per linked calendar account. Frontend filters/toggles per person.
- SQLite is the source of truth for the UI; a background sync worker reconciles against CalDAV every few minutes. Don't hit CalDAV live on every page render.
- Conflict resolution: last-write-wins — sufficient for a home device, don't build anything fancier.
- **Recurring events must be first-class from the start.** Most household calendar entries recur (trash day, lessons, school runs). The `Event` cache schema needs RRULE support — store the recurrence rule and exception dates, and expand occurrences over a rolling window rather than materializing infinite series. Retrofitting recurrence after the sync worker exists is far more painful than building it in; this lands in build step 2 and requires extending the current `Event` model.
- **Timezones & DST:** store event times as UTC plus original timezone; treat all-day events as dates, not midnight timestamps (the classic off-by-one-day bug across DST boundaries). Normalize at the sync layer so the frontend never does timezone math.
- **Offline behavior:** internet outages must degrade gracefully — the UI keeps serving the SQLite cache, and local edits queue for push when connectivity returns. The cache-as-source-of-truth design already enables this; the sync worker just has to be explicitly tolerant of unreachable CalDAV servers.
- Open item: each household member needs to hand over an app-specific password / OAuth grant for their calendar account — a real per-person setup step, not just a checkbox. Plan for it during rollout.

### Event emoji stickers (post-MVP)

- Goal: auto-decorate events with a relevant emoji from title/keyword matching (e.g. "Sarah's Birthday" → 🎂), with manual override per event for anything the matcher misses.
- Implementation sketch (later, not now): a keyword → emoji lookup table the backend applies when returning events, kept as a small config file so it's easy to extend without a migration. A manual override, when set, always wins over the auto-match.
- Initial keyword list to seed with:
  - birthday → 🎂
  - anniversary → 💍
  - wedding → 💒
  - baby shower → 🍼
  - graduation → 🎓
  - doctor / appointment (generic medical) → 🩺
  - dentist → 🦷
  - vacation / trip / flight → ✈️
  - haircut → ✂️
  - trash / recycling → 🗑️
  - game / practice (sports) → ⚽
  - concert / recital → 🎵
  - movie → 🎬
  - holiday (generic) → 🎉
  - Christmas → 🎄
  - Halloween → 🎃
  - Thanksgiving → 🦃
  - school / exam → 📚
  - work meeting → 💼
- Treat this as a starting point — refine once real household events show what's actually worth decorating rather than over-building the matcher up front.

## Weather

- **MVP.** Glance-info alongside the calendar view, not a section you navigate to separately.
- Use **Open-Meteo** — free, no API key or account, generous rate limits. No credential to manage for a feature that's just "what's it like outside."
- Backend polls on an interval (e.g. every 30–60 min) and caches the result; the frontend reads the cache via a `/weather` endpoint and never calls the provider directly. Keeps rate limits a non-issue, and weather still shows (stale but present) through a brief internet/provider outage — same resilience principle as the calendar cache.
- Location is static (the device doesn't move) — configure lat/long once at setup, no GPS/geolocation needed.
- Display: small persistent widget on the calendar view (current temp + icon), plus a short multi-day strip if it fits without crowding events.

## Recipes

- SQLite-backed: title, ingredients, steps, tags, favorite flag (per-person), image, source URL, prep/cook time, servings.
- Use `recipe-scrapers` (Python) to import recipes by pasting a URL from any of the hundreds of supported sites, instead of manual entry only — this is the difference between a recipe box people actually use and one that stays empty.
- Keep recipe IDs decoupled from calendar events now (don't embed recipe data into events) so a future "assign recipe to a day" meal-planning view isn't blocked later, without building it in v1.
- **MVP scope:** recipe box + favorites + URL import, as above. **Before starting that build step, do a dedicated requirements pass** rather than build straight from this sketch — the items below (GenAI menu planning, Android app) have real data-model implications (dietary tags per recipe/person, ingredient structuring that a shopping list can actually consume), and shaping the schema for them now is far cheaper than retrofitting after recipes already exist. This doesn't gate MVP timing — it's a planning step, not new scope.
- **Reference during that requirements pass:** [Grocy](https://github.com/grocy/grocy) (MIT-licensed, open source) already solves recipe→ingredient→shopping-list generation for a self-hosted household app. Not worth adopting wholesale — different stack (PHP), and it'd fight the kiosk/CalDAV/voice design already built here — but its data model for structured ingredients (quantity/unit/name, not free-text strings) and its REST API shape are worth a look when designing our own ingredient schema and the eventual shopping-list feature.
- **`MENU.md` (later addition):** a household dietary-restrictions/preferences file (allergies, who's vegetarian, weeknight time limits, etc.) used as context for GenAI-assisted weekly menu generation. This is personal/health-adjacent information — treat it like the encryption key, not like `PLAN.md`: keep it in the app's data directory (gitignored), never committed to the repo. The backend passes its contents to the LLM as context when generating menu suggestions.
- **Future: Android companion app** — browse/upload recipes from a phone, receive the week's shopping list. Real pivot from the "single device, LAN-only" assumption in Constraints; revisit backend network exposure (Security & credentials) when this gets built — likely a remote-access tunnel (Tailscale/WireGuard) rather than a publicly exposed API. Doesn't affect MVP.

### Requirements-pass outcomes (decided, now build-step scope)

- **Ingredients are lightly structured, not free text.** Each ingredient is stored as `{raw_text, name, quantity_text}` — `raw_text` is always the source of truth (verbatim from import or manual entry), `name`/`quantity_text` are best-effort derived for a future shopping list to group by. Checked Grocy first per the earlier reference note: it turns out Grocy requires fully manual structured entry (no parsing at all), so there's nothing to borrow there. Instead, use [`ingredient-parser-nlp`](https://github.com/strangetom/ingredient-parser) (MIT, actively maintained, Python-native, purpose-built for exactly this) to derive `name`/`quantity_text` from raw ingredient lines. Real constraints worth knowing: ~2s one-time model load per process, ~0.3s per ingredient line, and it downloads an NLTK model file on first use (needs internet once). Parsing failures fall back to `name = raw_text`, `quantity_text = null` — never blocks saving a recipe.
- **Dietary info is structured, not just tags**: separate `dietary_tags` (e.g. "vegetarian", "vegan") and `allergens` (e.g. "dairy", "nuts") list fields on Recipe, distinct from the general free-form `tags` field. `recipe-scrapers` exposes a `dietary_restrictions()` method, used best-effort on import — most sites don't populate it in their schema.org markup, so this is a bonus when present, not a dependency.
- **Recipe images download lazily, only on first favorite** — not at import time. `source_image_url` (the original site's image URL) is always captured on import; the image itself is only downloaded to local storage the first time *any* household member favorites the recipe, keeping SSD storage bounded to recipes people actually use rather than everything anyone ever pasted a URL for.
- **Deferred, not built this pass:** cook-mode step view (pure frontend, no schema impact, build whenever) and per-person notes/rating on a recipe (needs its own table — `recipe_id` + `person_name` + `note` + `rating`, deliberately *not* the same table as favorites, since unfavoriting shouldn't delete someone's note. Not added as a schema stub now since nothing would use it yet — add it when the feature actually gets built, same "shape the schema when you're about to use it" logic as everywhere else in this doc).

## Touch input / on-screen keyboard

- Don't rely on OS-level input methods (`squeekboard`/`onboard`) — flaky under Chromium kiosk, visually inconsistent with the app.
- Build the keyboard into the app itself (`simple-keyboard` JS library or similar), sliding up on input focus. Full control over styling/behavior.

## Ambient mode (photo carousel + motion wake)

- When idle (no touch/voice activity for N minutes), switch the dashboard to a full-screen photo carousel sourced from a local folder (synced from NAS or Google Photos periodically — not fetched live).
- Overnight: dim/sleep the screen on a schedule regardless of ambient mode, to avoid burn-in-adjacent wear and not lighting up a room at 3am.
- Wake triggers: touch (already have this for free) or the PIR/mmWave motion sensor (see Hardware). Motion wake should return to the *dashboard*, not just wake the carousel — the carousel is a screensaver, not a destination.
- Keep this feature decoupled from voice wake — voice wake word (Porcupine) should also exit ambient mode independently of the motion sensor.

## Voice assistant

Tiered, cheapest/lightest first — appropriate for 4GB RAM with cloud access assumed available:

1. **Wake word — local, always-on:** Porcupine (Picovoice). Tiny footprint, negligible CPU, safe to run continuously without competing for resources.
2. **Speech-to-text — cloud, on-demand only:** after wake word fires, stream the utterance to a cloud STT API rather than running Whisper/Vosk locally. On 4GB, local STT would be slow or would compete for RAM/CPU with the kiosk browser at the worst moment. Nothing streams until triggered, so this doesn't compromise the "cloud-assisted is fine" boundary.
3. **Intent handling — rule-based first, LLM fallback:** match common commands ("add an event," "what's for dinner," "read today's calendar") with simple rule/regex matching — fast, free, no round trip. Fall back to the Claude API for open-ended queries the rules don't cover.
4. **Text-to-speech — local:** Piper TTS, purpose-built for edge devices, light enough for the Pi 4, no need to send responses to the cloud.

## Security & credentials

- Backend stays LAN-only — no port-forwarding, no public internet exposure. Better yet: since the kiosk browser runs on the same Pi, bind the backend to `127.0.0.1` until remote/phone access is actually wanted — then the "unauthenticated API" question doesn't exist yet. When it does open to the LAN, note that anyone on the home WiFi (including guests) could read/modify data; a simple shared token for the frontend is enough at that point.
- OAuth tokens / app-specific passwords for multiple household members' calendar accounts are the sensitive asset here. Encrypt at rest: Python `cryptography` (Fernet symmetric encryption), with the encryption key stored outside the git repo, in a file with restricted permissions, on the SSD. This is enough for the actual threat model (physical/network access to a home device) — full database encryption (SQLCipher) is more than this needs.
- Never commit credentials, tokens, or the encryption key to git.

## Backups

- Nightly job (systemd timer or cron) copies the SQLite DB — and recipe/carousel images if practical — to the NAS. Off-device backup, since this becomes the household's calendar and recipe box and losing it is a real cost.
- Test the restore path once before relying on it — a backup that's never been restored is a hope, not a backup. Use SQLite's `.backup` command (or `VACUUM INTO`), not a raw file copy of a live DB, to avoid copying a mid-write snapshot.

## Schema migrations

- `SQLModel.metadata.create_all` only creates missing tables — it never alters existing ones. That's fine while developing (just recreate the dev DB), but **adopt Alembic before the first real household data lands on the Pi**, so later model changes (and there will be many — recurrence fields are already queued) don't force a wipe-and-relink of everyone's accounts.

## Deployment & updates

- Development happens on the Windows machine (conda env `home_organizer`); the Pi runs deployed code. The update path can be simple — a small deploy script doing `git pull` + `pip install -r requirements.txt` + `systemctl restart` is enough for a single device; no CI needed.
- Build the Svelte frontend on the dev machine and ship the static build output to the Pi. Don't make a 4GB Pi run npm builds.
- Pin dependency versions (freeze a lockfile) so rebuilding the Pi a year from now doesn't pull incompatible packages.

## Testing

- The one component that genuinely earns tests: CalDAV reconciliation logic (build step 2) — recurrence expansion, deletions, moved events, timezone normalization all have real edge cases. Test against fixture ICS files, not live accounts, so failures are reproducible.
- API endpoints get cheap coverage via FastAPI's `TestClient`. Don't chase UI test coverage on a home project.

## Reliability / ops

- Backend and Chromium kiosk run as systemd services with `Restart=on-failure`, so a crash doesn't require physically rebooting a wall-mounted device.
- Thermal self-monitoring (see Hardware) doubles as an early warning for fan failure. Monitor free disk space the same way — a full SSD (photo sync gone wrong, runaway logs) takes down SQLite writes.
- Kiosk setup gotchas to handle once, at provisioning: hide the mouse cursor, disable OS-level screen blanking (the app owns dimming), and launch Chromium with `--disable-session-crashed-bubble`/`--incognito` so a crash-restart doesn't strand a "Restore pages?" dialog on the wall.

## Future candidates (explicitly not v1)

- **Shopping list** — generated from recipe ingredients plus manual adds; the natural companion to recipes and a perfect voice target ("add milk to the list"). Likely the first post-v1 feature, and the eventual target of the Android app's "weekly shopping list" delivery.
- **Meal planning** — assign recipes to calendar days; the data model already leaves room for it. GenAI-assisted weekly menu generation (using `MENU.md` as dietary/preference context) builds on this.
- **Android companion app** — browse/upload recipes, receive the weekly shopping list. See Recipes section for the network-exposure implications this carries.
- **Kitchen timers via voice** — trivial once the voice pipeline exists, high daily value next to recipes.
- **Event reminders/announcements** — TTS callouts for upcoming events ("leave in 15 minutes").
- **Clock** on the dashboard and ambient screen (weather itself is now MVP — see Weather section).
- **Chores** — recurring per-person household tasks (dishes, trash, laundry), assignable and rotatable across household members, likely surfaced on the same dashboard as the calendar. Natural fit with the existing `person_name`-per-account pattern already used for calendars/recipe favorites. Overlaps with Grocy's chore-tracking feature and with dedicated tools like [Donetick](https://github.com/donetick/donetick) (natural-language task input, adaptive scheduling) — worth a look for data-model ideas when this gets built, same spirit as the Grocy reference in Recipes. Also a good voice-assistant target ("mark trash as done").

## Build order

1. FastAPI backend skeleton + SQLite schema (accounts, events cache, recipes) — no UI yet.
2. CalDAV sync worker — including RRULE/recurrence support and timezone normalization (extends the `Event` model) — tested against fixture ICS files first, then real Google/Apple accounts, before any frontend exists.
3. Svelte frontend + FullCalendar, read-only, talking to the backend over HTTP/WebSocket.
4. Calendar CRUD (add/edit/delete) round-tripped through to CalDAV.
5. Weather widget (backend polling + cache, frontend display alongside the calendar).
6. In-app virtual keyboard.
7. Recipes requirements pass (menu planning, `MENU.md`, Android app implications — see Recipes), then the recipes section + URL import.
8. Ambient mode (photo carousel, dim schedule, motion wake).
9. Voice pipeline — last, since it's the most independent piece and easiest to bolt on once the core app works.

Before first real deployment to the Pi (whenever real accounts/data go in): adopt Alembic (see Schema migrations) and set up the deploy script + systemd units.
