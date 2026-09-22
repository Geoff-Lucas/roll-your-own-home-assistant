#!/bin/sh
# Launched by the desktop session's autostart entry (see deploy/README.md
# step 5). Waits for the backend before opening the browser, since the
# desktop session and the systemd service start in parallel at boot and
# Chromium would otherwise land on a connection-refused error page.

until curl -sf http://localhost:8000/api/health >/dev/null; do
  sleep 1
done

# A kiosk has no use for desktop panels, and — because the app window below
# stops being fullscreen — they would pop up over the header whenever a touch
# lands on a screen edge. (Bring them back for maintenance: `xfce4-panel &`.)
xfce4-panel --quit 2>/dev/null

# Never blank the screen. Two independent X mechanisms can do it — the screen
# saver AND DPMS (power management) — so both need turning off, or the display
# still standbys after DPMS's own 10-minute timer even with the screen saver
# disabled. Blanking drops the HDMI signal: the monitor sleeps and its speakers
# go silent with it, so the wake word and alarms would be unseen and unheard.
# (The app can wake a sleeping screen, see app/display.py, so to let it sleep
# again just remove these two lines.)
xset s off
xset -dpms

# --password-store=basic: without it Chromium asks the system keyring for a
# password store, and on an auto-login session the keyring is locked, so an
# "Unlock Login Keyring" password dialog appears and grabs input. A kiosk
# stores no passwords, so bypass the keyring entirely.
chromium \
  --kiosk \
  --incognito \
  --password-store=basic \
  --noerrdialogs \
  --disable-infobars \
  --disable-translate \
  --no-first-run \
  --overscroll-history-navigation=0 \
  --disable-pinch \
  http://localhost:8000/ &
browser=$!

# The app window is full-screen-sized and frameless, but deliberately NOT in the
# window manager's "fullscreen" state: a focused fullscreen window is drawn
# above every other window, including the always-on-top window the Browser tab
# lays over the calendar area — so tapping the header would bury the browser.
# (--kiosk starts it fullscreen; this steps it back out without adding a frame.)
window=""
for _ in $(seq 1 60); do
  window=$(xdotool search --pid "$browser" --onlyvisible 2>/dev/null | tail -1)
  [ -n "$window" ] && break
  sleep 0.5
done
if [ -n "$window" ]; then
  set -- $(xdotool getdisplaygeometry)
  wmctrl -i -r "$window" -b remove,fullscreen
  wmctrl -i -r "$window" -e "0,0,0,$1,$2"
fi

wait "$browser"
