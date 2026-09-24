from datetime import date
from typing import Optional

from sqlmodel import Field, SQLModel


class MealPlan(SQLModel, table=True):
    """One day's assigned meal. Keyed by actual calendar date (not an
    abstract "Monday" slot) so history is naturally preserved as weeks pass
    and the planner just always shows whatever the current week's dates are.

    recipe_id is nullable — a day with no row, or a row with recipe_id=None,
    both mean "nothing assigned yet".
    """

    # Field name deliberately isn't `date` — Pydantic v2 chokes when a
    # field's name is exactly the same as its type annotation ("date: date"),
    # raising PydanticUserError at class-definition time.
    id: Optional[int] = Field(default=None, primary_key=True)
    plan_date: date = Field(index=True, unique=True)
    # Deleting a recipe leaves the day in place, just unassigned.
    recipe_id: Optional[int] = Field(default=None, foreign_key="recipe.id", ondelete="SET NULL")
