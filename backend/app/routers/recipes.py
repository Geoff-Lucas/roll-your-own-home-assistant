import re
from pathlib import Path
from typing import Annotated, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StringConstraints
from sqlmodel import select

from ..config import settings
from ..db import SessionDep
from ..models import Recipe, RecipeFavorite
from ..recipes.images import ensure_recipe_image_downloaded
from ..recipes.importer import import_recipe_from_url
from ..recipes.ingredient_parsing import parse_ingredient_line

router = APIRouter(prefix="/recipes", tags=["recipes"])


# What people type in front of a line when writing a recipe out by hand. A
# number only counts as numbering when a space follows its "." or ")", so a
# quantity like "1.5 cups" is left alone.
_BULLET = re.compile(r"^\s*[-*•·]+\s*")
_NUMBERING = re.compile(r"^\s*(?:step\s*\d+\s*[:.)-]?|\d+[.)](?=\s))\s*", re.IGNORECASE)


def _tidy_lines(lines: List[str], pattern: re.Pattern) -> List[str]:
    """Drop blank lines and a leading bullet or step number from each line."""
    return [cleaned for line in lines if (cleaned := pattern.sub("", line).strip())]


def _build_ingredients(raw_lines: List[str]) -> List[dict]:
    # The same parser the URL importer uses, so a typed recipe's ingredients
    # come out structured the same way (name + quantity, for a shopping list).
    return [parse_ingredient_line(line) for line in _tidy_lines(raw_lines, _BULLET)]


def _tidy_steps(lines: List[str]) -> List[str]:
    # Shown as a numbered list, so typed numbering would double up.
    return [_BULLET.sub("", line) for line in _tidy_lines(lines, _NUMBERING)]


def _tidy_tags(tags: List[str]) -> List[str]:
    seen, out = set(), []
    for tag in (t.strip().lower() for t in tags):
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Minutes = Optional[Annotated[int, Field(ge=0, le=24 * 60)]]
Servings = Optional[Annotated[int, Field(ge=1, le=100)]]


class RecipeCreate(BaseModel):
    title: Title
    ingredients: List[str] = []  # raw text lines — the server structures these, see _build_ingredients
    steps: List[str] = []
    tags: List[str] = []
    dietary_tags: List[str] = []
    allergens: List[str] = []
    source_url: Optional[str] = None
    prep_time_minutes: Minutes = None
    cook_time_minutes: Minutes = None
    servings: Servings = None


class RecipeUpdate(BaseModel):
    title: Optional[Title] = None
    ingredients: Optional[List[str]] = None
    steps: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    dietary_tags: Optional[List[str]] = None
    allergens: Optional[List[str]] = None
    source_url: Optional[str] = None
    prep_time_minutes: Minutes = None
    cook_time_minutes: Minutes = None
    servings: Servings = None


def _tidy(data: dict) -> dict:
    """Apply the typed-entry cleanup to whichever fields are present."""
    if "ingredients" in data:
        data["ingredients"] = _build_ingredients(data["ingredients"])
    if "steps" in data:
        data["steps"] = _tidy_steps(data["steps"])
    for field in ("tags", "dietary_tags", "allergens"):
        if data.get(field) is not None:
            data[field] = _tidy_tags(data[field])
    if isinstance(data.get("source_url"), str):
        data["source_url"] = data["source_url"].strip() or None
    return data


class RecipeImportRequest(BaseModel):
    url: str


@router.get("", response_model=List[Recipe])
def list_recipes(session: SessionDep, tag: Optional[str] = None) -> List[Recipe]:
    recipes = session.exec(select(Recipe)).all()
    if tag is not None:
        recipes = [r for r in recipes if tag in r.tags]
    return recipes


@router.get("/favorites", response_model=List[int])
def list_favorite_recipe_ids(person_name: str, session: SessionDep) -> List[int]:
    """Recipe IDs favorited by one person — lets the frontend compute
    per-card star state for "whoever's using the kiosk right now" without
    fetching every RecipeFavorite row for every recipe individually."""
    return session.exec(select(RecipeFavorite.recipe_id).where(RecipeFavorite.person_name == person_name)).all()


@router.post("", response_model=Recipe, status_code=201)
def create_recipe(payload: RecipeCreate, session: SessionDep) -> Recipe:
    recipe = Recipe(**_tidy(payload.model_dump()))
    session.add(recipe)
    session.commit()
    session.refresh(recipe)
    return recipe


@router.post("/import", response_model=Recipe, status_code=201)
def import_recipe(payload: RecipeImportRequest, session: SessionDep) -> Recipe:
    """Scrape a recipe from its source URL (recipe-scrapers supports
    hundreds of sites) rather than requiring manual entry — see PLAN.md
    Recipes section. Does not download the image; that only happens lazily
    on first favorite (see app/recipes/images.py)."""
    try:
        recipe = import_recipe_from_url(payload.url)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Couldn't import a recipe from that URL: {exc}") from exc
    session.add(recipe)
    session.commit()
    session.refresh(recipe)
    return recipe


@router.patch("/{recipe_id}", response_model=Recipe)
def update_recipe(recipe_id: int, payload: RecipeUpdate, session: SessionDep) -> Recipe:
    recipe = session.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    data = _tidy(payload.model_dump(exclude_unset=True))
    if data.get("title", "") is None:
        raise HTTPException(status_code=422, detail="A recipe needs a title")
    for field, value in data.items():
        setattr(recipe, field, value)
    session.add(recipe)
    session.commit()
    session.refresh(recipe)
    return recipe


@router.delete("/{recipe_id}", status_code=204)
def delete_recipe(recipe_id: int, session: SessionDep) -> None:
    recipe = session.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    image_path = recipe.image_path
    # Favorites go with it and meal-plan days are unassigned (the foreign keys'
    # ON DELETE rules, see the models).
    session.delete(recipe)
    session.commit()
    if image_path:
        # The copy downloaded on first favorite (app/recipes/images.py). Only
        # the file name is used, so a stored path can't point outside the folder.
        (settings.recipe_images_dir / Path(image_path).name).unlink(missing_ok=True)


@router.post("/{recipe_id}/favorite", status_code=204)
def favorite_recipe(recipe_id: int, person_name: str, session: SessionDep) -> None:
    recipe = session.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    existing = session.exec(
        select(RecipeFavorite).where(
            RecipeFavorite.recipe_id == recipe_id,
            RecipeFavorite.person_name == person_name,
        )
    ).first()
    if existing is None:
        session.add(RecipeFavorite(recipe_id=recipe_id, person_name=person_name))
        ensure_recipe_image_downloaded(recipe)  # no-op if already downloaded or no source image
        session.add(recipe)
        session.commit()


@router.delete("/{recipe_id}/favorite", status_code=204)
def unfavorite_recipe(recipe_id: int, person_name: str, session: SessionDep) -> None:
    existing = session.exec(
        select(RecipeFavorite).where(
            RecipeFavorite.recipe_id == recipe_id,
            RecipeFavorite.person_name == person_name,
        )
    ).first()
    if existing is not None:
        session.delete(existing)
        session.commit()
