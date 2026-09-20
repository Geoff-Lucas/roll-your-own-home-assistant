from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel

from ..time_utils import to_naive_utc


def _now() -> datetime:
    return to_naive_utc(datetime.now(timezone.utc))


class Location(SQLModel, table=True):
    """A place the weather widget can show. The *current* location is simply
    the most recently selected one (highest last_selected_at) — no separate
    "is current" flag to keep in sync. Rows not selected for a year are
    purged (see app/locations.py), except whichever one is current.

    Datetimes follow the project's naive-UTC convention (see time_utils.py).
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    latitude: float
    longitude: float
    created_at: datetime = Field(default_factory=_now)
    last_selected_at: datetime = Field(default_factory=_now, index=True)
