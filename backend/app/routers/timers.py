from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..audio.player import play_chime
from ..db import SessionDep
from ..timers import service

router = APIRouter(prefix="/timers", tags=["timers"])


class TimerCreate(BaseModel):
    kind: Literal["timer", "alarm", "stopwatch"]
    label: str = Field(default="", max_length=60)
    seconds: Optional[int] = Field(default=None, ge=1, le=service.MAX_TIMER_SECONDS)  # timers
    time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")  # alarms, "HH:MM" 24h
    repeat: Literal["none", "daily", "weekdays"] = "none"


class Snooze(BaseModel):
    minutes: int = Field(default=5, ge=1, le=120)


def _state(session) -> dict:
    return {"items": [service.describe(timer) for timer in service.list_all(session)]}


def _lookup(session, timer_id: int):
    try:
        return service.get(session, timer_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Timer not found") from exc


def _transition(action):
    """Bad moves (pausing something already paused, snoozing something that
    isn't ringing, ...) are a 409: the request is well-formed but the timer
    isn't in a state where it makes sense."""
    try:
        return action()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("")
def list_timers(session: SessionDep) -> dict:
    return _state(session)


@router.post("", status_code=201)
def create(payload: TimerCreate, session: SessionDep) -> dict:
    try:
        if payload.kind == "timer":
            if payload.seconds is None:
                raise HTTPException(status_code=422, detail="A timer needs `seconds`")
            timer = service.create_timer(session, payload.seconds, payload.label)
        elif payload.kind == "alarm":
            if payload.time is None:
                raise HTTPException(status_code=422, detail="An alarm needs `time` as HH:MM")
            timer = service.create_alarm(session, payload.time, payload.repeat, payload.label)
        else:
            timer = service.create_stopwatch(session, payload.label)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**service.describe(timer), "items": _state(session)["items"]}


@router.post("/{timer_id}/pause")
def pause(timer_id: int, session: SessionDep) -> dict:
    _transition(lambda: service.pause(session, _lookup(session, timer_id)))
    return _state(session)


@router.post("/{timer_id}/resume")
def resume(timer_id: int, session: SessionDep) -> dict:
    _transition(lambda: service.resume(session, _lookup(session, timer_id)))
    return _state(session)


@router.post("/{timer_id}/reset")
def reset(timer_id: int, session: SessionDep) -> dict:
    _transition(lambda: service.reset_stopwatch(session, _lookup(session, timer_id)))
    return _state(session)


@router.post("/{timer_id}/snooze")
def snooze(timer_id: int, payload: Snooze, session: SessionDep) -> dict:
    _transition(lambda: service.snooze(session, _lookup(session, timer_id), payload.minutes))
    return _state(session)


@router.post("/{timer_id}/dismiss")
def dismiss(timer_id: int, session: SessionDep) -> dict:
    _transition(lambda: service.dismiss(session, _lookup(session, timer_id)))
    return _state(session)


@router.delete("/{timer_id}", status_code=204)
def delete(timer_id: int, session: SessionDep) -> None:
    service.delete(session, _lookup(session, timer_id))


@router.post("/test-chime", status_code=204)
def test_chime() -> None:
    """Play the timer chime once — for checking that the speaker is wired up."""
    if not play_chime():
        raise HTTPException(status_code=503, detail="Couldn't play a sound (see the backend log)")
