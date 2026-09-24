from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class Recipe(SQLModel, table=True):
    """
    ingredients: list of {"raw_text": str, "name": str, "quantity_text": str|None}.
    raw_text is always the source of truth (verbatim from import or manual
    entry); name/quantity_text are best-effort derived (see
    app/recipes/ingredient_parsing.py) for a future shopping-list feature to
    group by — never load-bearing for anything else, so a bad parse never
    blocks saving a recipe.

    dietary_tags (e.g. "vegetarian") and allergens (e.g. "dairy") are
    separate from the general free-form `tags` field, so a future GenAI
    menu-planning feature (see PLAN.md MENU.md) can rely on them structurally
    rather than guessing which free-form tags are dietary-relevant.

    source_image_url is always captured on import if available; image_path
    (a locally downloaded copy) is only populated the first time any
    household member favorites the recipe — see app/recipes/images.py.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    ingredients: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    steps: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    tags: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    dietary_tags: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    allergens: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    source_url: Optional[str] = None
    source_image_url: Optional[str] = None
    image_path: Optional[str] = None
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    servings: Optional[int] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RecipeFavorite(SQLModel, table=True):
    """Per-person favorite, so each household member can favorite independently."""

    id: Optional[int] = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id", index=True, ondelete="CASCADE")
    person_name: str = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
