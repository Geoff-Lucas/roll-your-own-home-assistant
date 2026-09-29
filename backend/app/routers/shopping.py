import uuid
from datetime import date
from typing import List, Optional

import segno
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from sqlmodel import select

from ..config import settings
from ..db import SessionDep
from ..models import MealPlan, Recipe, ShoppingItem
from ..shopping import build_lines, build_mailto, list_entries
from ..time_utils import local_today, week_bounds

router = APIRouter(prefix="/shopping-list", tags=["shopping-list"])

# The list covers the rest of the meal planner's week: today's dinner through
# Saturday. Meals from earlier in the week are already eaten.

MANUAL = "manual:"


class ShoppingItemRead(BaseModel):
    key: str
    name: str
    quantity: str
    recipes: List[str]
    checked: bool
    manual: bool


class ShoppingListRead(BaseModel):
    start: date  # the first day whose meals are on the list (today)
    end: date
    meals: int  # how many planned meals it was built from
    items: List[ShoppingItemRead]


class ShareRead(BaseModel):
    qr: Optional[str]  # an SVG image as a data: URI; None when there's nothing left to buy
    included: int  # how many items the message holds
    left_out: int  # how many didn't fit (a very long list); the message says so too


class CheckedSet(BaseModel):
    key: str
    checked: bool


class ManualItem(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Type what to add")
        return value


def _build_list(session) -> ShoppingListRead:
    today = local_today()
    week_start, week_end = week_bounds(today)

    # Ticks from earlier weeks have done their job.
    stale = session.exec(select(ShoppingItem).where(ShoppingItem.manual == False, ShoppingItem.week_start < week_start)).all()  # noqa: E712
    for row in stale:
        session.delete(row)
    if stale:
        session.commit()

    plan = session.exec(
        select(MealPlan)
        .where(MealPlan.plan_date >= today, MealPlan.plan_date <= week_end, MealPlan.recipe_id != None)  # noqa: E711
        .order_by(MealPlan.plan_date)
    ).all()
    meals = []
    for row in plan:
        recipe = session.get(Recipe, row.recipe_id)
        if recipe is not None:
            meals.append((recipe.title, recipe.ingredients))

    ticked = {
        row.key
        for row in session.exec(
            select(ShoppingItem).where(ShoppingItem.manual == False, ShoppingItem.week_start == week_start, ShoppingItem.checked == True)  # noqa: E712
        ).all()
    }
    items = [
        ShoppingItemRead(key=line.key, name=line.name, quantity=line.quantity, recipes=line.recipes, checked=line.key in ticked, manual=False)
        for line in build_lines(meals)
    ]
    for row in session.exec(select(ShoppingItem).where(ShoppingItem.manual == True).order_by(ShoppingItem.created_at, ShoppingItem.id)).all():  # noqa: E712
        items.append(ShoppingItemRead(key=row.key, name=row.name, quantity="", recipes=[], checked=row.checked, manual=True))

    return ShoppingListRead(start=today, end=week_end, meals=len(meals), items=items)


@router.get("", response_model=ShoppingListRead)
def get_shopping_list(session: SessionDep) -> ShoppingListRead:
    return _build_list(session)


@router.get("/share", response_model=ShareRead)
def share_shopping_list(session: SessionDep) -> ShareRead:
    """A QR code that opens an email with what's left to buy, for a phone to scan.
    Ticked items are left out: they're already in the trolley."""
    current = _build_list(session)
    todo = [item for item in current.items if not item.checked]
    if not todo:
        return ShareRead(qr=None, included=0, left_out=0)

    header = f"Shopping list, {current.start:%b} {current.start.day} - {current.end:%b} {current.end.day}"
    link, included = build_mailto(list_entries((i.name, i.quantity) for i in todo), header, settings.shopping_email_to)
    code = segno.make(link, error="l", micro=False)
    return ShareRead(qr=code.svg_data_uri(scale=1, border=4, dark="#000", light="#fff"), included=included, left_out=len(todo) - included)


@router.put("/checked", status_code=204)
def set_checked(payload: CheckedSet, session: SessionDep) -> None:
    """Tick an item off, or put it back. Works on a key from the list, ingredient or added by hand."""
    if payload.key.startswith(MANUAL):
        row = session.exec(select(ShoppingItem).where(ShoppingItem.key == payload.key, ShoppingItem.manual == True)).first()  # noqa: E712
        if row is None:
            raise HTTPException(status_code=404, detail="No such item")
        row.checked = payload.checked
        session.add(row)
    else:
        week_start, _ = week_bounds(local_today())
        row = session.exec(select(ShoppingItem).where(ShoppingItem.key == payload.key, ShoppingItem.week_start == week_start)).first()
        if payload.checked and row is None:
            session.add(ShoppingItem(key=payload.key, name=payload.key, checked=True, week_start=week_start))
        elif payload.checked:
            row.checked = True
            session.add(row)
        elif row is not None:
            session.delete(row)
    session.commit()


@router.post("/manual", response_model=ShoppingItemRead, status_code=201)
def add_manual_item(payload: ManualItem, session: SessionDep) -> ShoppingItemRead:
    row = ShoppingItem(key=f"{MANUAL}{uuid.uuid4().hex[:10]}", name=payload.name, manual=True)
    session.add(row)
    session.commit()
    return ShoppingItemRead(key=row.key, name=row.name, quantity="", recipes=[], checked=False, manual=True)


@router.delete("/manual/{key}", status_code=204)
def remove_manual_item(key: str, session: SessionDep) -> None:
    row = session.exec(select(ShoppingItem).where(ShoppingItem.key == key, ShoppingItem.manual == True)).first()  # noqa: E712
    if row is None:
        raise HTTPException(status_code=404, detail="No such item")
    session.delete(row)
    session.commit()
