from contextlib import contextmanager
from datetime import date, datetime
from typing import Iterator, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator
from sqlmodel import select

from ..config import settings
from ..db import SessionDep
from ..models import Account, Event
from ..sync.locks import AccountBusy, account_lock
from ..sync.caldav_client import (
    CalDAVError,
    create_event_on_server,
    delete_event_on_server,
    event_search_window,
    update_event_on_server,
)
from ..sync.ics_builder import build_ics, new_uid
from ..time_utils import to_naive_utc

router = APIRouter(prefix="/events", tags=["events"])

# NOTE: reads operate on the local cache; the CalDAV sync worker (app/sync/)
# is what pulls real calendar accounts into it, including expanding
# recurring series into concrete occurrences — by the time a row lands here
# it's always a single concrete occurrence, never an unbounded series.
#
# Writes (below) round-trip to CalDAV, but only for non-recurring events:
# creating/editing/deleting a single occurrence of a recurring series has
# real RFC 5545 complexity (RECURRENCE-ID overrides, EXDATE bookkeeping)
# that's deliberately out of scope here. Recurring events remain read-only
# until that's built.


class EventCreate(BaseModel):
    account_id: int
    title: str
    description: Optional[str] = None
    location: Optional[str] = None

    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    timezone: Optional[str] = None

    all_day: bool = False
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    # Manual prep-reminder flag — see app/reminders/detection.py. Leave
    # reminder_lead_days unset to fall back to keyword auto-detection instead.
    reminder_lead_days: Optional[int] = None
    reminder_text: Optional[str] = None

    @model_validator(mode="after")
    def check_time_fields(self) -> "EventCreate":
        if self.all_day:
            if self.start_date is None or self.end_date is None:
                raise ValueError("all-day events require start_date and end_date")
        else:
            if self.start_time is None or self.end_time is None:
                raise ValueError("timed events require start_time and end_time")
        return self


class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    timezone: Optional[str] = None
    all_day: Optional[bool] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    reminder_lead_days: Optional[int] = None
    reminder_text: Optional[str] = None


@contextmanager
def _account_turn(account_id: int) -> Iterator[None]:
    """Hold the account's sync lock across the server write and the local
    commit, so a sync can't fetch before the write and reconcile after it
    (see app/sync/locks.py). Waits for an in-progress sync, usually a second
    or two; a hung one gets a 503 rather than a hung request."""
    try:
        with account_lock(account_id, timeout=settings.calendar_write_wait_seconds):
            yield
    except AccountBusy as exc:
        raise HTTPException(status_code=503, detail="The calendar is busy syncing — try again in a moment") from exc


def _get_event(session: SessionDep, event_id: int) -> Event:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


def _reload_event(session: SessionDep, event_id: int) -> Event:
    """Read the event afresh once it's our turn: a sync may have changed or
    removed it while this request waited."""
    session.expunge_all()
    return _get_event(session, event_id)


def _get_writable_account(session: SessionDep, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if not account.caldav_url:
        raise HTTPException(status_code=400, detail="Account has no linked CalDAV calendar to write to")
    return account


def _compute_recurrence_id(event: Event) -> str:
    """The identity key a fresh sync will assign this exact occurrence.

    `recurring_ical_events` (see sync/ics_parser.py) gives *every* occurrence
    a recurrence_id equal to its own instant — even a plain non-recurring
    event, not just real recurring-series overrides. A locally created or
    edited event has to be given that same value up front; otherwise the
    next sync cycle fetches this event back with a recurrence_id we never
    set, fails to match it to the row we already have (whose key is
    (uid, None)), and reconciles it as "removed and re-added" — silently
    replacing our row with a new one under a new id. Caught live against a
    real Google account: a row created, then edited a few seconds later by
    id, had already been swapped out from under that id by the background
    sync in between.
    """
    return event.start_date.isoformat() if event.all_day else event.start_time.isoformat()


@router.get("", response_model=List[Event])
def list_events(
    session: SessionDep,
    account_id: Optional[int] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> List[Event]:
    query = select(Event)
    if account_id is not None:
        query = query.where(Event.account_id == account_id)
    rows = session.exec(query).all()

    if start is None and end is None:
        return rows

    # Event.start_time/end_time are always naive-UTC (see Event's
    # validator); a client-supplied timestamp may be tz-aware, so normalize
    # before comparing.
    start = to_naive_utc(start) if start is not None else None
    end = to_naive_utc(end) if end is not None else None

    results = []
    for row in rows:
        if row.all_day:
            if start is not None and row.end_date < start.date():
                continue
            if end is not None and row.start_date > end.date():
                continue
        else:
            if start is not None and row.end_time < start:
                continue
            if end is not None and row.start_time > end:
                continue
        results.append(row)
    return results


@router.post("", response_model=Event, status_code=201)
def create_event(payload: EventCreate, session: SessionDep) -> Event:
    account = _get_writable_account(session, payload.account_id)

    # uid is minted here, not accepted from the client — CalDAV has no
    # server-side UID generation, and the client owns choosing one.
    event = Event(**payload.model_dump(), uid=new_uid())
    event.recurrence_id = _compute_recurrence_id(event)

    with _account_turn(account.id):
        try:
            create_event_on_server(account, build_ics(event))
        except CalDAVError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        session.add(event)
        session.commit()
        session.refresh(event)
    return event


@router.patch("/{event_id}", response_model=Event)
def update_event(event_id: int, payload: EventUpdate, session: SessionDep) -> Event:
    with _account_turn(_get_event(session, event_id).account_id):
        event = _reload_event(session, event_id)
        if event.rrule is not None:
            raise HTTPException(status_code=400, detail="Editing recurring events isn't supported yet")

        account = _get_writable_account(session, event.account_id)
        # Must be captured before mutating event below — the resource on the
        # server is still at the pre-edit time until this update succeeds, so
        # searching around the *new* time could miss it. See
        # caldav_client.event_search_window's docstring.
        search_window = event_search_window(event)

        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(event, field, value)
        event.recurrence_id = _compute_recurrence_id(event)

        try:
            update_event_on_server(account, event.uid, search_window, build_ics(event))
        except CalDAVError as exc:
            # event's in-memory fields were mutated above but never committed,
            # so they're discarded when the request's session closes — the
            # local cache stays consistent with what the server actually has.
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        session.add(event)
        session.commit()
        session.refresh(event)
    return event


@router.delete("/{event_id}", status_code=204)
def delete_event(event_id: int, session: SessionDep) -> None:
    with _account_turn(_get_event(session, event_id).account_id):
        event = _reload_event(session, event_id)
        if event.rrule is not None:
            raise HTTPException(status_code=400, detail="Deleting recurring events isn't supported yet")

        account = _get_writable_account(session, event.account_id)

        try:
            delete_event_on_server(account, event.uid, event_search_window(event))
        except CalDAVError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        session.delete(event)
        session.commit()
