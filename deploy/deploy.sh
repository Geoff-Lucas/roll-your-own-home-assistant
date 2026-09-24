#!/usr/bin/env bash
# Push a code update from the dev machine to the kiosk. Run from git-bash,
# WSL, or any POSIX shell — see deploy/README.md for first-time setup.
#
# Usage: deploy/deploy.sh geoff@h-asst.local
#
# Needs only ssh + tar locally (git-bash on Windows has no rsync). Files are
# streamed to a staging dir on the target, then the *target's* rsync mirrors
# them into place — so deletions propagate and .venv/data/.env are preserved.
set -euo pipefail

TARGET="${1:?Usage: deploy.sh user@hostname}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE='~/.home_organizer_stage'

echo "==> Building frontend"
(cd "$REPO_ROOT/frontend" && npm run build)

echo "==> Uploading code"
# shellcheck disable=SC2029
ssh "$TARGET" "rm -rf $STAGE && mkdir -p $STAGE/backend $STAGE/frontend-dist $STAGE/deploy"
tar -C "$REPO_ROOT/backend" \
  --exclude='.venv' --exclude='data' --exclude='__pycache__' \
  --exclude='.pytest_cache' --exclude='.env' -cf - . \
  | ssh "$TARGET" "tar -C $STAGE/backend -xf -"
tar -C "$REPO_ROOT/frontend/dist" -cf - . | ssh "$TARGET" "tar -C $STAGE/frontend-dist -xf -"
tar -C "$REPO_ROOT/deploy" -cf - . | ssh "$TARGET" "tar -C $STAGE/deploy -xf -"

echo "==> Syncing into place, installing dependencies, restarting"
# shellcheck disable=SC2029
ssh "$TARGET" "
  set -e
  mkdir -p home_organizer/backend home_organizer/frontend/dist home_organizer/deploy
  rsync -a --delete --exclude .venv --exclude data --exclude .env $STAGE/backend/ home_organizer/backend/
  rsync -a --delete $STAGE/frontend-dist/ home_organizer/frontend/dist/
  rsync -a --delete $STAGE/deploy/ home_organizer/deploy/
  rm -rf $STAGE
  cd home_organizer/backend
  [ -d .venv ] || python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
  if systemctl list-unit-files home-organizer.service >/dev/null 2>&1 && systemctl cat home-organizer >/dev/null 2>&1; then
    sudo systemctl restart home-organizer
  else
    echo '(home-organizer service not installed yet — skipping restart)'
  fi
"

echo "==> Done"
