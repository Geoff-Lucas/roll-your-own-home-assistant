from datetime import date, datetime, timedelta
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from ..db import SessionDep
from ..models import Event
from ..reminders.detection import compute_reminder

router = APIRouter(prefix="/reminders", tags=["reminders"])


class ReminderEntry(BaseModel):
    event_id: int
    title: str
    event_date: date
    days_until: int
    text: str


def _event_date(event: Event) -> date:
    return event.start_date if event.all_day else event.start_time.date()


@router.get("", response_model=List[ReminderEntry])
def list_reminders(session: SessionDep, lookahead_days: int = 60) -> List[ReminderEntry]:
    # local server date, same convention as app/ambient/schedule.py — this
    # is about which day the household is on, not the naive-UTC convention
    # Event storage uses for precise instants.
    today = datetime.now().date()
    window_end = today + timedelta(days=lookahead_days)

    entries: List[ReminderEntry] = []
    for event in session.exec(select(Event)).all():
        reminder = compute_reminder(event)
        if reminder is None:
            continue

        event_date = _event_date(event)
        if event_date < today or event_date > window_end:
            continue

        days_until = (event_date - today).days
        if days_until > reminder["lead_days"]:
            continue

        entries.append(
            ReminderEntry(
                event_id=event.id,
                title=event.title,
                event_date=event_date,
                days_until=days_until,
                text=reminder["text"],
            )
        )

    entries.sort(key=lambda e: e.days_until)
    return entries


@router.post("/{event_id}/dismiss", status_code=204)
def dismiss_reminder(event_id: int, session: SessionDep) -> None:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    event.reminder_dismissed = True
    session.add(event)
    session.commit()
