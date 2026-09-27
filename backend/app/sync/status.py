"""Whether each calendar account is syncing, so a failure shows on screen.

Google calendar sync once failed for a day with only the log to say so: the
kiosk just kept showing a frozen calendar. The sync worker records every
attempt here, and the page shows a warning for accounts in trouble.

Not every failure deserves a warning. A server that's briefly unreachable
recovers by itself, so that only counts once it has lasted a while
(sync_warning_after_minutes). An expired sign-in or a rejected password never
fixes itself, so those count at once.

In memory only: after a restart the first sync (at startup) fills it in again.
"""

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from ..config import settings


@dataclass
class _Health:
    last_success: Optional[datetime] = None
    failing_since: Optional[datetime] = None
    kind: Optional[str] = None  # "relink" | "password" | "unreachable"


_health: dict[int, _Health] = {}
_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def classify(exc: BaseException) -> str:
    """What kind of trouble an exception from a sync means."""
    text = f"{type(exc).__name__}: {exc}"
    if "RefreshError" in text or "invalid_grant" in text:
        return "relink"  # Google ended the app's sign-in; only signing in again fixes it
    if "AuthorizationError" in text or "401" in text:
        return "password"  # a CalDAV password (e.g. iCloud app-specific) was rejected
    return "unreachable"


def record_success(account_id: int, now: Optional[datetime] = None) -> None:
    with _lock:
        health = _health.setdefault(account_id, _Health())
        health.last_success, health.failing_since, health.kind = now or _now(), None, None


def record_failure(account_id: int, exc: BaseException, now: Optional[datetime] = None) -> None:
    with _lock:
        health = _health.setdefault(account_id, _Health())
        health.failing_since = health.failing_since or now or _now()
        health.kind = classify(exc)


def forget(account_id: int) -> None:
    with _lock:
        _health.pop(account_id, None)


def problems(
    accounts: Iterable, now: Optional[datetime] = None, last_synced: Optional[dict[int, datetime]] = None
) -> list[dict]:
    """Accounts whose trouble is worth showing, as plain dicts for the API.

    last_synced: when each account's events were last confirmed by a sync,
    from the database (the newest Event.last_synced_at). Unlike this module's
    memory it survives a restart, so "hasn't updated since" stays true.
    """
    now = now or _now()
    patience = timedelta(minutes=settings.sync_warning_after_minutes)
    last_synced = last_synced or {}
    out = []
    with _lock:
        for account in accounts:
            health = _health.get(account.id)
            if health is None or health.failing_since is None:
                continue
            if health.kind == "unreachable" and now - health.failing_since < patience:
                continue
            known = [t for t in (health.last_success, last_synced.get(account.id)) if t is not None]
            last_updated = max(known) if known else None
            out.append(
                {
                    "account_id": account.id,
                    "display_name": account.display_name,
                    "person_name": account.person_name,
                    "kind": health.kind,
                    "failing_since": health.failing_since.isoformat(),
                    "last_updated": last_updated.isoformat() if last_updated else None,
                    # Renewing a Google sign-in in place (routers/google_oauth.py).
                    "relink_url": (
                        f"http://localhost:8000/api/google-oauth/start?account_id={account.id}"
                        if health.kind == "relink" and account.provider == "google"
                        else None
                    ),
                }
            )
    return out
