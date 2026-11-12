#!/usr/bin/env bash
# Adds the recipes waiting in the NAS inbox — see deploy/README.md "Recipes from
# the PC". Run as root by home-organizer-recipes.service every 15 minutes
# (mounting the share needs root); safe to run by hand the same way:
#   sudo systemctl start home-organizer-recipes
#
# The Windows Recipe Importer drops each recipe in
# $NAS_BASE/recipes/inbox on the share; app/recipes/inbox.py (run here as the
# kiosk's own user, so the photos it stores belong to the app) adds them and
# moves each file to inbox/imported or inbox/failed.
#
# Like the backup, the share is mounted only for the length of the run, so a NAS
# that is down costs one skipped run, never a hung kiosk.
set -euo pipefail

NAS_SHARE="${NAS_SHARE:-//LUCAS-HOME-NAS.local/HomeBulk}"
NAS_BASE="${NAS_BASE:-home_organizer}"
NAS_CREDENTIALS="${NAS_CREDENTIALS:-/etc/home-organizer/nas.credentials}"
: "${APP_USER:?set APP_USER to the account the app runs as}"
: "${BACKEND_DIR:?set BACKEND_DIR to the backend folder (where .env lives)}"
PYTHON="${PYTHON:-$BACKEND_DIR/.venv/bin/python}"

# A login is used if the file exists; without one the share is mounted as a guest, which
# the NAS's HomeBulk share allows (asked for as a user named "guest" with an empty password:
# this NAS refuses the plain "guest" mount option).
if [ -r "$NAS_CREDENTIALS" ]; then
  auth="credentials=$NAS_CREDENTIALS"
else
  auth="username=guest,password="
fi

work=$(mktemp -d /run/home-organizer-recipes.XXXXXX)
mnt="$work/nas"
mkdir "$mnt"
cleanup() {
  mountpoint -q "$mnt" && umount "$mnt"
  rm -rf "$work"
}
trap cleanup EXIT

# The user owns the files on the share for this run, so the import can move
# them to imported/ and failed/ without being root.
mount -t cifs "$NAS_SHARE" "$mnt" \
  -o "$auth,vers=3.1.1,iocharset=utf8,noperm,soft,echo_interval=10,uid=$(id -u "$APP_USER"),gid=$(id -g "$APP_USER")"

inbox="$mnt/$NAS_BASE/recipes/inbox"
if [ ! -d "$inbox" ]; then
  echo "No recipe inbox yet ($NAS_BASE/recipes/inbox) — nothing sent from the PC"
  exit 0
fi

# Nothing waiting is the usual case; don't start Python (slow on the Pi) for it.
if ! compgen -G "$inbox/*.json" >/dev/null; then
  exit 0
fi

cd "$BACKEND_DIR"
runuser -u "$APP_USER" -- "$PYTHON" -m app.recipes.inbox "$inbox"
