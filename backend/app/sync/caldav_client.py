from datetime import datetime, timedelta
from typing import List

import caldav
import icalendar

from ..config import settings
from ..models import Account, Event
from ..security.crypto import decrypt
from .google_oauth import get_valid_access_token


class CalDAVError(RuntimeError):
    """Raised when an account can't be reached or has no usable calendar.

    Deliberately a distinct type so callers (the events API) can translate
    it into a clean 502 rather than a raw 500 with a library traceback.
    """


def _is_configured(account: Account) -> bool:
    if not account.caldav_url:
        return False
    if account.oauth_refresh_token:
        return True
    return bool(account.username and account.encrypted_credential)


def _principal(account: Account) -> caldav.Principal:
    if not _is_configured(account):
        raise CalDAVError(f"Account {account.id} has no linked CalDAV calendar configured")

    if account.oauth_refresh_token:
        # Google CalDAV requires OAuth exclusively — see app/sync/google_oauth.py.
        refresh_token = decrypt(account.oauth_refresh_token)
        access_token = get_valid_access_token(refresh_token)
        client = caldav.DAVClient(
            url=account.caldav_url, password=access_token, auth_type="bearer", timeout=settings.caldav_timeout_seconds
        )
    else:
        password = decrypt(account.encrypted_credential)
        client = caldav.DAVClient(
            url=account.caldav_url, username=account.username, password=password, timeout=settings.caldav_timeout_seconds
        )
    return client.principal()


def _first_calendar(account: Account) -> caldav.Calendar:
    """Resolve the calendar to read/write for an account.

    MVP simplification: always uses the account's first calendar. An
    account with multiple calendars (e.g. "Home" and "Work" under one
    iCloud login) only gets read/written through the first one — fine for
    a single-calendar-per-person household setup, but a real limitation
    worth revisiting if that comes up.
    """
    try:
        principal = _principal(account)
        calendars = principal.calendars()
    except CalDAVError:
        raise
    except Exception as exc:
        raise CalDAVError(f"Couldn't reach CalDAV server for account {account.id}: {exc}") from exc
    if not calendars:
        raise CalDAVError(f"Account {account.id} has no calendars on the server")
    return calendars[0]


def fetch_account_ics(account: Account, window_start: datetime, window_end: datetime) -> List[bytes]:
    """Fetch raw ICS resources for an account's calendars within a window.

    One entry per CalDAV resource — a recurring series and its overrides
    travel together as a single resource, which is what `ics_parser` expects.
    `expand=False` deliberately leaves recurrence expansion to us (see
    ics_parser.parse_ics_resource) rather than the server/library doing it,
    so results are consistent regardless of server quirks.

    Raises on connection/auth failure — callers must catch this per-account
    so one unreachable or misconfigured account doesn't block the others
    (see app/sync/worker.py).
    """
    if not _is_configured(account):
        return []

    principal = _principal(account)
    raw_resources: List[bytes] = []
    for cal in principal.calendars():
        results = cal.search(start=window_start, end=window_end, event=True, expand=False)
        for result in results:
            data = result.data
            raw_resources.append(data.encode() if isinstance(data, str) else data)
    return raw_resources


def event_search_window(event: Event) -> tuple[datetime, datetime]:
    """Bounds to search for an event's existing CalDAV resource within.

    Callers must compute this from the event's state *before* applying any
    local edit to start_time/start_date — the resource on the server is
    still at the old time until the update actually succeeds, so searching
    around the new (not-yet-saved) time would miss it. events.py's
    update_event captures this immediately after loading the row, before
    setattr-ing any payload changes onto it.
    """
    if event.all_day:
        start = datetime.combine(event.start_date, datetime.min.time())
        end = datetime.combine(event.end_date, datetime.min.time())
    else:
        start = event.start_time
        end = event.end_time
    return start - timedelta(days=1), end + timedelta(days=1)


def _find_calendar_object(calendar: caldav.Calendar, uid: str, window_start: datetime, window_end: datetime):
    """Locate the CalDAV resource for a known event by UID, within a tight
    window around where we already know it lives.

    Deliberately doesn't use caldav's own `get_event_by_uid()`: (1) it does
    an *unbounded* search when no date range is given, which falls back to
    expanding recurrences from year 1 — `datetime.min.astimezone()` raises
    `OSError: [Errno 22] Invalid argument` on Windows (confirmed live; Linux
    doesn't have this limitation, so it may be fine on the Pi, but there's
    no reason to depend on that). (2) tested live against a real Google
    account: Google's CalDAV server doesn't actually honor server-side UID
    filtering — a bounded search with `uid=...` still returned every event
    in range. So: reuse the same bounded, unfiltered search fetch_account_ics
    already uses successfully, and match the UID ourselves.
    """
    results = calendar.search(start=window_start, end=window_end, event=True, expand=False)
    for result in results:
        data = result.data
        raw = data.encode() if isinstance(data, str) else data
        parsed = icalendar.Calendar.from_ical(raw)
        for component in parsed.walk("VEVENT"):
            if str(component.get("UID")) == uid:
                return result
    raise CalDAVError(f"Event {uid} not found on CalDAV server")


def create_event_on_server(account: Account, ical_text: str) -> None:
    """Create a new event resource. `ical_text` must already contain a
    unique UID (see ics_builder.new_uid) — CalDAV has no server-side UID
    generation, the client owns it."""
    calendar = _first_calendar(account)
    try:
        calendar.add_event(ical=ical_text)
    except Exception as exc:
        raise CalDAVError(f"Couldn't create event on CalDAV server: {exc}") from exc


def update_event_on_server(account: Account, uid: str, search_window: tuple[datetime, datetime], ical_text: str) -> None:
    calendar = _first_calendar(account)
    try:
        obj = _find_calendar_object(calendar, uid, *search_window)
        obj.data = ical_text
        obj.save()
    except CalDAVError:
        raise
    except Exception as exc:
        raise CalDAVError(f"Couldn't update event {uid} on CalDAV server: {exc}") from exc


def delete_event_on_server(account: Account, uid: str, search_window: tuple[datetime, datetime]) -> None:
    calendar = _first_calendar(account)
    try:
        obj = _find_calendar_object(calendar, uid, *search_window)
        obj.delete()
    except CalDAVError:
        raise
    except Exception as exc:
        raise CalDAVError(f"Couldn't delete event {uid} on CalDAV server: {exc}") from exc
