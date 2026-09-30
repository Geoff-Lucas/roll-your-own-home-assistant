#!/bin/sh
# Brings the kiosk app's window back after the in-app "🖥️ Desktop" button
# minimized it (see app/system.py) — there is no taskbar to click on a kiosk,
# so deploy/kiosk.sh installs a desktop icon that runs this instead.
#
# windowactivate deiconifies, raises and focuses in one step; if the window
# is gone entirely (crashed, or the session restarted without going through
# kiosk.sh), there is nothing to activate, so start it fresh instead.
export DISPLAY=:0

if xdotool search --name "Home Organizer" windowactivate; then
  # The backend brought the panel back when the app was minimized and hides it
  # again on its own once the window is restored; doing it here as well makes
  # it instant, and covers the backend having restarted in between.
  xfce4-panel --quit 2>/dev/null
  exit 0
fi

exec sh "$(dirname "$0")/kiosk.sh"
