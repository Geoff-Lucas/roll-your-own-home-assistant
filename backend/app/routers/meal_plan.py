from datetime import date, timedelta
from typing import List, Optional, Tuple

from fastapi import APIRouter
from pydantic import BaseModel
from sqlmodel import select

from ..db import SessionDep
from ..models import MealPlan, Recipe
from ..time_utils import local_today

router = APIRouter(prefix="/meal-plan", tags=["meal-plan"])


class MealPlanEntry(BaseModel):
    # Not named `date` — see app/models/meal_plan.py for why that field name
    # is off-limits on a Pydantic model annotated with the `date` type.
    plan_date: date
    recipe_id: Optional[int] = None
    recipe_title: Optional[str] = None
    recipe_image: Optional[str] = None


class MealPlanSet(BaseModel):
    recipe_id: Optional[int] = None


def _current_week_bounds() -> Tuple[date, date]:
    today = local_today()  # the household's date, in its timezone setting
    start = today - timedelta(days=(today.weekday() + 1) % 7)  # back up to the most recent Sunday
    return start, start + timedelta(days=6)


def _entry_for(session, plan_date: date, recipe_id: Optional[int]) -> MealPlanEntry:
    recipe = session.get(Recipe, recipe_id) if recipe_id else None
    return MealPlanEntry(
        plan_date=plan_date,
        recipe_id=recipe.id if recipe else None,
        recipe_title=recipe.title if recipe else None,
        recipe_image=(recipe.image_path or recipe.source_image_url) if recipe else None,
    )


@router.get("", response_model=List[MealPlanEntry])
def get_meal_plan(session: SessionDep, start: Optional[date] = None, end: Optional[date] = None) -> List[MealPlanEntry]:
    if start is None or end is None:
        start, end = _current_week_bounds()

    rows = session.exec(select(MealPlan).where(MealPlan.plan_date >= start, MealPlan.plan_date <= end)).all()
    by_date = {row.plan_date: row for row in rows}

    entries = []
    current = start
    while current <= end:
        row = by_date.get(current)
        entries.append(_entry_for(session, current, row.recipe_id if row else None))
        current += timedelta(days=1)
    return entries


@router.put("/{plan_date}", response_model=MealPlanEntry)
def set_meal_plan(plan_date: date, payload: MealPlanSet, session: SessionDep) -> MealPlanEntry:
    row = session.exec(select(MealPlan).where(MealPlan.plan_date == plan_date)).first()
    if row is None:
        row = MealPlan(plan_date=plan_date, recipe_id=payload.recipe_id)
    else:
        row.recipe_id = payload.recipe_id
    session.add(row)
    session.commit()
    session.refresh(row)

    return _entry_for(session, plan_date, row.recipe_id)
