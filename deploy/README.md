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

## Before this holds real household data

A few things from PLAN.md are explicitly meant to happen before — not
during — the first real deployment:

- **Adopt Alembic** (see PLAN.md "Schema migrations") — `create_all` only
  creates missing tables, it never alters existing ones. Every model change
  since would currently mean wiping the DB.
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
