# Provisioning the kiosk machine

Target: an x86_64 mini PC (Ryzen 5 3500U / 16GB / 512GB NVMe, hostname
`h-asst`) running **Debian with the XFCE desktop** (verified on Debian 13
"trixie", Python 3.13 — all of `requirements.txt` installs cleanly there),
driving the 27" 2K portrait touchscreen over HDMI. (This replaced the original Raspberry Pi 4B
plan — the Pi was judged too underpowered.)

**Caveat up front:** the desktop/kiosk parts of this guide have not yet been
run end-to-end on the real machine — everything here follows standard Debian,
systemd and XFCE practice, but treat it as a first draft to verify on the
device, the same way the motion sensor and hardware-dimming code elsewhere in
this project are flagged as unverified without real hardware. (The motion
sensor in particular is a Pi-GPIO feature; on this machine it simply stays
disabled via the `BadPinFactory` fallback in `app/ambient/motion.py` unless
you wire up a USB/other alternative later.)

Why Debian and not Ubuntu: Ubuntu ships Chromium only as a snap, which is
slower to start and has sandboxing quirks that make it a worse fit for a
kiosk. Debian ships a normal `chromium` deb.

## 1. Install Debian 12

Use the netinst image. At the software-selection step choose only:

- **Xfce** (desktop environment)
- **SSH server**
- **standard system utilities**

Create a regular user (this guide writes `<user>`). If you set a root
password during install, Debian will *not* install `sudo` — fix that once:

```bash
su -
apt install -y sudo
usermod -aG sudo <user>
exit    # then log out and back in
```

If SSH server wasn't selected at install: `sudo apt install -y openssh-server`.
Ethernet is preferred over WiFi (see PLAN.md Hardware).

## 2. First boot

SSH in (`ssh <user>@h-asst.local`) and do the one-time base setup:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y python3-venv python3-dev build-essential \
  chromium git rsync curl unclutter xdotool wmctrl
```

(`xdotool` and `wmctrl` are what the Browser tab uses to place its window.)

Set up auto-login so the machine boots straight into the desktop with no
password prompt, via a drop-in file `/etc/lightdm/lightdm.conf.d/50-autologin.conf`
(create the directory if missing):

```ini
[Seat:*]
autologin-user=<user>
autologin-user-timeout=0
```

Then stop the screen from blanking/locking (the app does its own overnight
dimming, so the OS shouldn't). Done over SSH, as verified on `h-asst`:

```bash
export DISPLAY=:0
for p in "dpms-enabled:bool:false" "blank-on-ac:int:0" "dpms-on-ac-sleep:int:0" "dpms-on-ac-off:int:0"; do
  IFS=: read name type val <<<"$p"
  xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/$name --create -t $type -s $val
done
# Debian's XFCE ships light-locker, which would lock the kiosk — disable it:
pkill light-locker
printf "[Desktop Entry]\nType=Application\nName=light-locker\nHidden=true\n" > ~/.config/autostart/light-locker.desktop
```

Because the panel is portrait, rotate the display (Settings → Display →
Rotation) — on `h-asst` that's **Left** — and then **rotate the touch input
to match; it does not follow automatically.** The ILITEK controller reports
in the panel's native landscape orientation, so without this every tap lands
90° away from where you touched. On `h-asst` this is the fix, verified by
tapping all four corners and reading back the pointer position
(`xdotool getmouselocation`):

```bash
sudo mkdir -p /etc/X11/xorg.conf.d
sudo tee /etc/X11/xorg.conf.d/99-ilitek-touch-rotation.conf >/dev/null <<'EOF'
Section "InputClass"
    Identifier "ILITEK touch rotation"
    MatchProduct "ILITEK"
    Driver "libinput"
    Option "CalibrationMatrix" "0 -1 1 1 0 0 0 0 1"
EndSection
EOF
sudo reboot
```

Notes for a different rotation or panel: the matrix above is for a
**left** rotation (`0 -1 1 1 0 0`); for **right** use `0 1 0 -1 0 1`. It must
be libinput's `CalibrationMatrix` — setting the generic `Coordinate
Transformation Matrix` with `xinput set-prop` had no effect on touch-driven
pointer events here. Adjust `MatchProduct` to your controller's name
(`xinput list`). To experiment without rebooting, set it live with
`xinput set-prop <id> "libinput Calibration Matrix" 0 -1 1 1 0 0 0 0 1`
(all nine values are required).

### Audio (timer chimes now, voice replies later)

Sound goes through **one configurable ALSA device**, `HOME_ORGANIZER_AUDIO_DEVICE`
in `backend/.env` (used with `aplay -D`; default `"default"`). On `h-asst` that
is the monitor's own speakers over HDMI, and the thing to know is that **the
speakers are only there while the screen is awake**:

- When the screen blanks (X's screen saver, after 10 minutes idle) the HDMI link
  drops and the monitor sleeps. The audio hardware then sees no monitor
  (`/proc/asound/card0/eld#*` say `monitor_present 0`), PulseAudio swaps its HDMI
  output for a null sink that swallows sound, and nothing can be heard. Awake,
  the same files say `monitor_present 1`, `eld_valid 1` and PulseAudio offers a
  proper HDMI sink. (An earlier version of these notes called this a driver bug;
  it was measured with the screen asleep.)
- **Use `pulse`** (`HOME_ORGANIZER_AUDIO_DEVICE=pulse`), not a raw device such as
  `plughw:0,3`. When the screen wakes PulseAudio grabs the HDMI device for about
  5 seconds while it re-detects the monitor, and a raw `aplay` in that window
  fails with "Device or resource busy". Going through PulseAudio has no such
  fight, and the browser's sound uses the same path.
- The service needs `XDG_RUNTIME_DIR=/run/user/1000` (it is in
  `home-organizer.service`; use your user's id from `id -u`) to reach that
  PulseAudio. Without it `aplay -D pulse` says "Connection refused" and the app
  is silent. Don't write it as `%U`: in a system service that means root.
- **Waking the screen.** `app/display.py` wakes it (`xset s reset`) when the
  "Hey Jarvis" wake word is heard and each time a timer or alarm chimes, then waits
  1.5 s (`HOME_ORGANIZER_DISPLAY_WAKE_SETTLE_SECONDS`) for the monitor to resync,
  so the acknowledgement tone or chime isn't lost. It knows the screen is asleep
  when PulseAudio's default output is the null sink. Touching the screen wakes it
  as usual. For now the kiosk doesn't sleep at all: `deploy/kiosk.sh` runs
  `xset s off` at login. Remove that line (and log in again, or run `xset s 600`)
  to let the screen blank after 10 idle minutes; the wake-up above then takes over.
- To find the right raw output on a machine without PulseAudio, play something
  distinct on each HDMI device and listen — e.g. `aplay -D plughw:0,3 x.wav`,
  then `0,7`, `0,8` (list them with `aplay -l`) — and put it in `.env`.

Check it from the kiosk with `curl -X POST http://127.0.0.1:8000/api/timers/test-chime`
(plays the timer chime once). The USB microphone needs no setup — it is
PulseAudio's default input.

### Voice assistant (tap the 🎤 in the header)

Tap-to-talk: microphone → **local** speech-to-text (faster-whisper) → command
matching → reply spoken and shown on screen. What you say never leaves the
house. Commands today: timers, alarms and the stopwatch, the time and date, and
the weather (see `backend/app/voice/skills/`). Pieces, and how to set each up:

- **Microphone.** Set `HOME_ORGANIZER_MIC_DEVICE` to the ALSA capture device,
  by *name* so it survives the USB card number changing between boots (find it
  with `arecord -l`): `plughw:CARD=Microphone,DEV=0` on `h-asst`. Needs `arecord`
  (alsa-utils).
- **Speech model (one-time download).** The app never downloads it behind your
  back. Run once, from `~/home_organizer/backend`:

  ```bash
  .venv/bin/python -m app.voice.setup          # ~145 MB, models/ under backend/data/voice
  .venv/bin/python -m app.voice.setup --check  # report what is installed; downloads nothing
  ```

  Until it is installed, tapping 🎤 says so on screen. The model is chosen with
  `HOME_ORGANIZER_VOICE_STT_MODEL` (default `base.en`; `small.en` is more accurate
  and slower). Speech recognition needs the `faster-whisper` package, which is
  in `requirements.txt`.
- **Voice for replies.** `sudo apt install -y espeak-ng` gives a robotic but
  zero-setup voice, used automatically. A natural-sounding **Piper** voice is
  used instead once one is chosen. Piper itself is the `piper-tts` pip package
  (in `requirements.txt`, found automatically beside the app's Python); a
  voice is a separate download, about 60 MB for a medium one, fetched by a
  command you run:

  ```bash
  cd ~/home_organizer/backend
  .venv/bin/python -m app.voice.setup --piper en_US-amy-medium   # lands in data/voice/piper
  echo 'HOME_ORGANIZER_VOICE_PIPER_MODEL=en_US-amy-medium' >> .env && sudo systemctl restart home-organizer
  ```

  `HOME_ORGANIZER_VOICE_PIPER_MODEL` is the voice's name (or a path to a
  `.onnx` file). Browse voices, with audio samples, at
  <https://rhasspy.github.io/piper-samples/>. `GET /api/voice/status` shows
  `"speaker": "piper"` when it is in use. The app keeps the voice loaded (about
  90 MB when loaded at startup, growing to around 200 MB once it has spoken), so
  a reply renders in roughly 0.3 s;
  running Piper as a separate program for every reply cost about 2 s each time.
  Replies are played through `HOME_ORGANIZER_AUDIO_DEVICE` (see Audio above).
- **Hands-free "Hey Jarvis".** Set `HOME_ORGANIZER_VOICE_WAKEWORD_ENABLED=true`
  and restart. A background listener keeps the microphone open and feeds it,
  80 ms at a time, to a small local model (openWakeWord's `hey_jarvis`, about
  3 ms of CPU per frame). The audio is only compared against that model and
  discarded — nothing is recorded or recognized until the phrase is heard; then
  a short tone plays, the panel opens, and it works exactly like a tap (if the
  screen was asleep it is woken first — see Audio). It is
  off by default because it holds the microphone open. The model ships inside
  the `openwakeword` package, which is pinned to 0.4.0: newer releases need
  `tflite-runtime`, which has no build for Python 3.13.
  Tune with `HOME_ORGANIZER_VOICE_WAKEWORD_THRESHOLD` (default `0.5`; lower is
  more sensitive and triggers on more things). `GET /api/voice/status` shows
  `recent_peak_level` (loudest audio the mic heard in the last ~10 s) and
  `recent_peak_score` (how close the model got): a quick way to tell "the mic
  can't hear me" from "it heard me but didn't recognize the phrase".
- **Saying "stop" while something rings.** While a timer or alarm is going
  off you can just say "stop", "dismiss" or "snooze" (or "snooze for ten
  minutes") — no wake word. The kiosk has no echo cancellation and can't listen
  through its own chime, so the two take turns: chime, a beat for the echo to die
  away, then a ~3 second listening window (`HOME_ORGANIZER_VOICE_RING_WINDOW_SECONDS`),
  then the next chime. The microphone is only opened while something is ringing.
  What counts is deliberately narrow: only a short (six words or fewer), explicit
  stop/dismiss/snooze, so "okay", "thanks" or people talking can't silence an
  alarm, and no other command is acted on without the wake word. Anything it
  hears and ignores is kept in `GET /api/voice/history` (entries marked
  `"via": "ringing"`) so false triggers can be diagnosed. Turn it off with
  `HOME_ORGANIZER_VOICE_RING_LISTEN=false`.
- **Changing the reply voice.** With espeak-ng: `HOME_ORGANIZER_VOICE_ESPEAK_VOICE`
  (e.g. `en-us+f3` for a woman's voice, `en-gb`, `en-us+m3`) and
  `HOME_ORGANIZER_VOICE_ESPEAK_SPEED` (words per minute, default 160). List the
  options with `espeak-ng --voices=en`. Natural-sounding voices need Piper (see
  above). Of the two US voices tried on the kiosk's monitor speakers, `amy`
  sounded clearer than `lessac`, which reverberated more.
- **Checking it.** `curl http://127.0.0.1:8000/api/voice/status` says what is
  missing. Everything after speech recognition can be tried without a
  microphone: `curl -X POST http://127.0.0.1:8000/api/voice/text -H "Content-Type: application/json" -d '{"text":"what time is it"}'`
  runs the command and speaks the reply.
- **Claude API fallback for open-ended questions.** Timers, the clock and the
  weather are answered locally by rule-based matching (see
  `app/voice/router.py`); anything else ("what's a good substitute for
  buttermilk?") gets `"Sorry, I don't know how to help with that yet."` unless
  this is turned on. **Off by default, and the one place anything voice-related
  leaves the house** — the *text* of the question (never audio) goes to
  Anthropic's Messages API, along with today's date/time, the cached weather
  and the current location for grounding. To turn it on:

  ```
  HOME_ORGANIZER_VOICE_CLAUDE_ENABLED=true
  HOME_ORGANIZER_VOICE_CLAUDE_API_KEY=sk-ant-...
  ```

  `HOME_ORGANIZER_VOICE_CLAUDE_MODEL` picks the model (default
  `claude-sonnet-5`; `claude-haiku-4-5-20251001` answers faster and is cheaper,
  worth it if the reply's latency matters more than its polish — this is a
  kiosk reply, not a chat). Replies are capped short (one or two spoken
  sentences) and there's no conversation memory yet — every question is
  answered on its own; follow-ups ("what about tomorrow?") aren't understood
  as continuations. `GET /api/voice/status` shows `"claude_fallback": true`
  once both settings are in place.

  **Web search.** Claude's training data has a cutoff, so on its own it can't
  answer things like "what's the score" or "what's in the news today."
  `HOME_ORGANIZER_VOICE_CLAUDE_WEB_SEARCH=true` gives it Anthropic's hosted
  web-search tool — Claude decides on its own whether a question needs it;
  when it does, the search runs as part of the same request, no extra
  round trip. Off by default: a further step out than plain Q&A, since search
  queries leave the house too, and each search Claude runs is billed on top
  of the reply. `HOME_ORGANIZER_VOICE_CLAUDE_WEB_SEARCH_MAX_USES` (default 3)
  caps how many searches one question can trigger.

## 3. Get the code onto the machine

For the very first deploy, clone directly on the machine:

```bash
git clone <your-repo-url> ~/home_organizer
cd ~/home_organizer/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` — at minimum set `HOME_ORGANIZER_WEATHER_LATITUDE`/`_LONGITUDE`
and `HOME_ORGANIZER_WEATHER_LOCATION_NAME` (e.g. `"Fairfax, VA"`) for your
actual location. These only **seed the first entry**: after that the weather
location is chosen from the on-screen picker (tap the location at the top
right), which keeps recently used places for quick reselection and deletes
any not picked for a year (`HOME_ORGANIZER_LOCATION_RETENTION_DAYS`, default
365; the location currently showing is never deleted). Changing these env
values later has no effect once a location exists.

**Existing accounts do not carry over.** Neither the SQLite DB
(`backend/data/`, excluded from rsync) nor the encryption key
(`~/.home_organizer/secret.key`, deliberately outside the repo) exists on this
machine yet, and stored calendar credentials can't be decrypted without the
original key. Re-add each calendar account here. For Google accounts, do the
OAuth flow from a browser *on this machine* (the XFCE session works for that
— one more benefit of having a desktop), because the redirect URI is
`http://localhost:8000/api/google-oauth/callback` and `localhost` has to
mean the machine running the backend.

After this first clone, use `deploy/deploy.sh` from your dev machine for
every subsequent update instead (see step 6) — no need to `git pull` on the
machine by hand each time.

## 4. Backend as a systemd service

The unit file assumes user `pi` and `/home/pi/home_organizer`. Install it
with your real username substituted in:

```bash
sed "s#/home/pi/#/home/$USER/#g; s#^User=pi\$#User=$USER#" \
  ~/home_organizer/deploy/home-organizer.service \
  | sudo tee /etc/systemd/system/home-organizer.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now home-organizer
sudo systemctl status home-organizer   # confirm it's active
curl http://127.0.0.1:8000/api/health  # confirm it's answering
```

Already installed before the Browser tab existed? Re-run the `sed … | sudo tee` line
above and `sudo systemctl daemon-reload && sudo systemctl restart home-organizer`:
the unit now sets `DISPLAY` and keeps `/usr/bin` on `PATH`, which the Browser
tab needs.

## 5. Kiosk autostart

Register the kiosk launcher as an XFCE autostart application:

```bash
mkdir -p ~/.config/autostart
cp ~/home_organizer/deploy/home-organizer-kiosk.desktop ~/.config/autostart/
```

`deploy/kiosk.sh` waits for the backend's health endpoint before launching
fullscreen Chromium, so it doesn't race the systemd service at boot. To hide
the mouse pointer while idle (touch-only use), add `unclutter` as a second
autostart entry (Settings → Session and Startup → Application Autostart →
command `unclutter -idle 1 -root`).

Reboot (`sudo reboot`); the machine should come up straight into the
fullscreen kiosk. To get out of it for maintenance: plug in a keyboard and
press `Alt+F4`, or just SSH in. To disable kiosk autostart temporarily,
delete `~/.config/autostart/home-organizer-kiosk.desktop`.

If it doesn't come up: check `sudo systemctl status home-organizer` first
(most failures are the backend not running, not the browser), then
`~/.xsession-errors`.

### Minimizing to the desktop

The **🖥️ Desktop** button in the header (`POST /api/system/minimize`, handled
by `app/system.py`) minimizes whichever window is focused — always this app's
own kiosk window, since a click on it can only reach the backend while that
window has focus. It's for a quick look at the desktop (plugging something in,
a file manager) without leaving the kiosk session.

Getting back is the part a kiosk doesn't have a taskbar for, so
`deploy/kiosk.sh` installs a **"Home Organizer" icon on the desktop** every
login, running `deploy/return-to-kiosk.sh`: it brings the existing window
back (deiconify, raise, focus, all via `xdotool windowactivate`) or, if the
window is gone entirely — crashed, or the session restarted without going
through `kiosk.sh` — starts the kiosk fresh instead. Only works on the kiosk
itself (needs a display and `xdotool`); everywhere else `/system/minimize`
reports 503, same convention as the Browser tab's endpoints.

Getting a `.desktop` launcher to just run, with no clicks in between, took
three things (all verified on this machine, XFCE 4.20 / gvfs 1.57):
- **`gio set FILE metadata::trusted true`** — without it, the first
  double-click shows an "Untrusted application launcher" dialog instead of
  running it. This is what "Mark As Secure And Launch" on that dialog sets by
  hand.
- **`gio set FILE metadata::xfce-exe-checksum "$(sha256sum FILE | cut -d' ' -f1)"`**
  — a checksum of the file's own bytes that has to match *right now*, so
  it has to be set fresh every time the file's content changes (every login,
  since `kiosk.sh` rewrites it). Undocumented as far as we could find; found by
  diffing `gio info -a "*"` before and after clicking "Mark As Secure And
  Launch" by hand. Without this one, `metadata::trusted` alone still isn't
  enough — the same dialog keeps coming back.
- **`StartupNotify=false`** in the `.desktop` file — without it, XFCE waits
  for a new window to appear (the usual sign a launcher worked) and reports a
  false "Launch Error: Timeout was reached", because this launcher only
  refocuses the *existing* window rather than opening a new one.

### The Browser tab

The **Browser** tab in the header shows a real web browser under the toolbar,
for looking up recipes. It is **not** an embedded frame — sites such as Google,
Allrecipes and NYT Cooking refuse to be framed, and a framed page's address
can't be read by the app. Instead the backend launches a second Chromium
(profile in `backend/data/browser-profile/`, so logins persist — keep it out of
backups), lays it over the page area as a frameless always-on-top window, and
steers it over the DevTools protocol (bound to `127.0.0.1` only). The toolbar's
address field takes URLs *or* search terms (anything that isn't a URL becomes a
Google search), and **Add to recipes** reads the page's URL from the browser and
runs it through the recipe importer. Typing *inside* web pages needs a physical
keyboard — the on-screen keyboard only works in the app's own fields.

Three things make the layering work, all handled by `deploy/kiosk.sh`:

- The app window is full-screen-sized and frameless but **not** in the window
  manager's fullscreen state. A focused fullscreen window is drawn above every
  other window — including always-on-top ones — so a tap on the header would
  otherwise bury the browser.
- The browser window is created with `--kiosk` (Chromium draws no frame in
  kiosk mode; a normal or `--app` window gets a title bar that can't be
  removed), then taken out of fullscreen and placed with `wmctrl`.
- The XFCE panels are quit on login, since without fullscreen protection they
  would pop up over the header when a screen edge is touched.

While the Browser tab is open the photo carousel is suspended (touches inside
the browser window aren't visible to the app), and the overnight dimming does
not apply to the browser window.

### Headless alternative

If you'd rather not run a desktop at all, `deploy/xinitrc` is a
no-window-manager setup: install `xserver-xorg xinit` instead of XFCE, use
console auto-login, copy it to `~/.xinitrc`, and start it from `~/.bash_profile`
with `exec startx -- -nocursor` on tty1. (That variant doesn't wait for the
backend, so on a fast machine add the same `curl` wait loop from `kiosk.sh`.)

## 6. Ongoing updates

Set up passwordless SSH once from the dev machine, so `deploy.sh` doesn't
prompt on every internal `ssh`/`rsync` call:

```bash
ssh-keygen -t ed25519            # skip if you already have a key
ssh-copy-id <user>@h-asst.local
```

`deploy.sh` also runs `sudo systemctl restart` over SSH, where a password
prompt would hang. Allow just that one command without a password (on the
machine):

```bash
echo "$USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart home-organizer" \
  | sudo tee /etc/sudoers.d/home-organizer
```

Then, from the dev machine (git-bash or WSL; only `ssh` and `tar` are needed
locally — the script streams files to a staging dir and the *target's* rsync
mirrors them into place, so no local rsync is required; `npm` must be on the
PATH, on Windows that means the conda env's Node):

```bash
deploy/deploy.sh <user>@h-asst.local
```

This builds the frontend locally (never on the target — see PLAN.md
"Deployment & updates"), rsyncs both backend code and the frontend build,
reinstalls any changed Python dependencies, and restarts the service. The
kiosk browser picks up frontend changes on its next reload (`F5` with a
keyboard attached, or restart the session); `systemctl restart` picks up
backend changes immediately.

**Database changes** need no separate step: the backend applies any pending
migrations (`backend/migrations/`) itself at startup, before serving anything.
After changing a model, write the migration on the dev machine and commit it
with the change:

```bash
cd backend
alembic revision --autogenerate -m "add calories to recipe"
```

Read the generated file before committing — autogenerate misses some things
(a rename comes out as drop + add, which loses the column's data).
`tests/test_migrations.py` fails if a model changes without a migration.

## Before this holds real household data

A few things from PLAN.md are explicitly meant to happen before — not
during — the first real deployment:

- ~~Adopt Alembic~~ — done (see "Database changes" above). The kiosk's
  existing database was adopted at the baseline migration with its data
  intact; a copy from just before is at `backend/data/home_organizer.db.pre-migrations`.
- ~~Verify the CalDAV write-back path against a real account~~ — done, against
  a real Google account (see PLAN.md Calendar section for what broke and got
  fixed along the way). Still worth a smoke test against iCloud/generic
  CalDAV specifically before relying on it, since Google's quirks (no
  server-side UID filtering) may not be universal — but the write-back
  mechanism itself is proven, not just mocked.
- **Set up the nightly NAS backup** (PLAN.md "Backups") and actually test a
  restore once.
- **Populate `ambient_photos/`** (rsync from NAS or a Google Photos
  downloader script — the app only ever reads that directory, see
  `app/ambient/photos.py`).
