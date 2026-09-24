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

# Let the screen sleep after two idle hours (no touch, keyboard or mouse).
# Sleeping drops the HDMI signal, so the monitor's speakers go quiet too; the
# app wakes it first for "Hey Jarvis" and alarms (app/display.py). Two X
# mechanisms can blank the screen; only the screen saver does it here, and
# DPMS stays off so its own 10-minute default can't cut in. (The app must not
# run `xset dpms force on` while DPMS is off: that quietly turns it back on.)
SCREEN_SLEEP_SECONDS=7200
xset s "$SCREEN_SLEEP_SECONDS" "$SCREEN_SLEEP_SECONDS"
xset -dpms

# A "🖥️ Desktop" button in the app (see app/system.py) minimizes it to look at
# the desktop underneath; since there's no taskbar on a kiosk to click to bring
# it back, install a desktop icon that does (deploy/return-to-kiosk.sh).
# Rewritten every login so an updated script or icon always takes effect.
kiosk_dir=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$HOME/Desktop"
chmod +x "$kiosk_dir/return-to-kiosk.sh"
cat > "$HOME/Desktop/home-organizer.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Home Organizer
Comment=Return to the kiosk app
Exec=$kiosk_dir/return-to-kiosk.sh
Icon=video-display
Terminal=false
StartupNotify=false
EOF
chmod +x "$HOME/Desktop/home-organizer.desktop"
# Two things XFCE checks before it will run a desktop-file launcher without
# asking (verified on this machine): metadata::trusted, and a checksum of the
# file's own bytes that must match right now — so it has to be set fresh every
# time the file's content changes, which is every login. Without both, the
# first double-click shows an "Untrusted application launcher" dialog instead
# of running it ("Mark As Secure And Launch" on that dialog sets the same two
# things by hand). StartupNotify=false above matters too: without it, XFCE
# waits for a new window to appear and reports a false "Timeout was reached"
# error, since this launcher only refocuses the existing one.
gio set "$HOME/Desktop/home-organizer.desktop" metadata::trusted true 2>/dev/null || true
gio set "$HOME/Desktop/home-organizer.desktop" metadata::xfce-exe-checksum \
  "$(sha256sum "$HOME/Desktop/home-organizer.desktop" | cut -d' ' -f1)" 2>/dev/null || true

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
