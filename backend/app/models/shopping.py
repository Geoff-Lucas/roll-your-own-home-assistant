from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class ShoppingItem(SQLModel, table=True):
    """What the shopping list remembers. The list itself isn't stored: it's built
    fresh from this week's meal plan every time (see app/shopping.py), so it
    follows the plan. Two kinds of row are kept:

    - a *checked* ingredient (manual=False): its `key` is the ingredient's
      normalized name and `week_start` the week it was ticked off in. Ticking
      is for one week only ("I have onions" shouldn't carry into next week's
      list), so rows from earlier weeks are dropped as the list is read.
    - an item added by hand (manual=True), like paper towels: it stays until
      it's removed, whatever the week. Its `key` is "manual:" plus a random id.
    """

    __table_args__ = (UniqueConstraint("key", "week_start"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(index=True)
    name: str
    manual: bool = False
    checked: bool = False
    week_start: Optional[date] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
