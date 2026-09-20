"""The small shared vocabulary of the voice assistant."""

from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Optional

from sqlmodel import Session


@dataclass(frozen=True)
class Reply:
    """What the assistant says back. The same text is shown on screen and
    spoken, so it is written to read naturally aloud (no symbols or tables)."""

    text: str
    understood: bool = True


@dataclass
class Context:
    """Everything a command may need, passed in rather than reached for, so
    a command is a plain function of (what was said, this context) and can be
    tested with a fake clock, an in-memory database and canned weather."""

    session: Session
    now: datetime  # naive UTC, the project's convention (see time_utils.py)
    tz: tzinfo
    weather: Optional[dict] = None  # app.weather's cached widget shape
    location_name: Optional[str] = None

    @property
    def now_local(self) -> datetime:
        from datetime import timezone

        return self.now.replace(tzinfo=timezone.utc).astimezone(self.tz)
