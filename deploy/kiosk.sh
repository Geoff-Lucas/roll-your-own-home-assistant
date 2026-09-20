#!/bin/sh
# Launched by the desktop session's autostart entry (see deploy/README.md
# step 5). Waits for the backend before opening the browser, since the
# desktop session and the systemd service start in parallel at boot and
# Chromium would otherwise land on a connection-refused error page.

until curl -sf http://localhost:8000/api/health >/dev/null; do
  sleep 1
done

exec chromium \
  --kiosk \
  --incognito \
  --noerrdialogs \
  --disable-infobars \
  --disable-translate \
  --no-first-run \
  --overscroll-history-navigation=0 \
  --disable-pinch \
  http://localhost:8000/
