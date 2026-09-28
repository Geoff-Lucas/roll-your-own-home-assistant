#!/usr/bin/env bash
# Nightly copy of the kiosk's own data to the NAS — see deploy/README.md
# "Backups to the NAS". Run as root by home-organizer-backup.service (mounting
# the share needs root); safe to run by hand the same way:
#   sudo systemctl start home-organizer-backup
#
# What goes where, under $NAS_BASE on the share:
#   recipes/database/home_organizer-YYYY-MM-DD.db   the whole app database
#       (recipes, meal plan, calendars, reminders...), one per day, the last
#       $KEEP_DAYS kept. Calendar passwords/tokens in it are encrypted with a
#       key that is NOT copied (~/.home_organizer/secret.key), so a restore
#       without that key means signing in to the calendars again.
#   recipes/images/    recipe photos
#   photos/ambient/    the carousel photos
# Images are only ever added or updated on the NAS, never deleted there, so a
# photo removed from the kiosk by mistake is still on the NAS.
#
# The share is mounted only for the length of the run, so a NAS that is down
# or rebooting costs one missed night (the run fails and says why in
# `journalctl -u home-organizer-backup`), never a hung kiosk.
set -euo pipefail

NAS_SHARE="${NAS_SHARE:-//LUCAS-HOME-NAS.local/Home}"
NAS_BASE="${NAS_BASE:-home_organizer}"
NAS_CREDENTIALS="${NAS_CREDENTIALS:-/etc/home-organizer/nas.credentials}"
KEEP_DAYS="${KEEP_DAYS:-30}"
: "${DATA_DIR:?set DATA_DIR to the backend data directory}"
PYTHON="${PYTHON:-python3}"

if [ ! -r "$NAS_CREDENTIALS" ]; then
  echo "No NAS credentials at $NAS_CREDENTIALS — see deploy/README.md 'Backups to the NAS'" >&2
  exit 1
fi

work=$(mktemp -d /run/home-organizer-backup.XXXXXX)
mnt="$work/nas"
mkdir "$mnt"
cleanup() {
  mountpoint -q "$mnt" && umount "$mnt"
  rm -rf "$work"
}
trap cleanup EXIT

# A consistent copy of the live database (SQLite's online backup — the app
# keeps running), checked before it goes anywhere.
snapshot="$work/home_organizer.db"
"$PYTHON" - "$DATA_DIR/home_organizer.db" "$snapshot" <<'PY'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
result = dst.execute("PRAGMA integrity_check").fetchone()[0]
if result != "ok":
    sys.exit(f"database copy failed its integrity check: {result}")
PY

mount -t cifs "$NAS_SHARE" "$mnt" \
  -o "credentials=$NAS_CREDENTIALS,iocharset=utf8,noperm,soft,echo_interval=10"

base="$mnt/$NAS_BASE"
if [ ! -d "$base" ]; then
  echo "$NAS_SHARE has no $NAS_BASE folder — not creating one in the wrong place" >&2
  exit 1
fi
mkdir -p "$base/recipes/database" "$base/recipes/images" "$base/photos/ambient"

# Written under a temporary name first, so a copy cut off halfway never looks
# like a good backup.
target="$base/recipes/database/home_organizer-$(date +%F).db"
cp "$snapshot" "$target.partial"
mv -f "$target.partial" "$target"

# -rt, not -a: the NAS share has no Unix owners or permissions to keep.
# --modify-window: SMB timestamps are coarser than ext4's.
copy_new() { rsync -rt --modify-window=2 "$1/" "$2/"; }
copy_new "$DATA_DIR/recipe_images" "$base/recipes/images"
copy_new "$DATA_DIR/ambient_photos" "$base/photos/ambient"

# Only this script's own dated files are ever deleted.
find "$base/recipes/database" -maxdepth 1 -type f -name 'home_organizer-*.db' \
  -mtime "+$KEEP_DAYS" -print -delete

echo "Backed up to $NAS_SHARE/$NAS_BASE: $(basename "$target"), $(ls "$base/recipes/images" | wc -l) recipe images, $(ls "$base/photos/ambient" | wc -l) photos"
