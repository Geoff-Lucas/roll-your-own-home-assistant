from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from ..config import settings
from ..db import SessionDep
from ..models import Recipe, RecipeFavorite
from ..recipes.images import ensure_recipe_image_downloaded
from ..recipes.importer import import_recipe_from_url
from ..recipes.ingredient_parsing import parse_ingredient_line

router = APIRouter(prefix="/recipes", tags=["recipes"])


def _build_ingredients(raw_lines: List[str]) -> List[dict]:
    return [parse_ingredient_line(line) for line in raw_lines]


class RecipeCreate(BaseModel):
    title: str
    ingredients: List[str] = []  # raw text lines — the server structures these, see _build_ingredients
    steps: List[str] = []
    tags: List[str] = []
    dietary_tags: List[str] = []
    allergens: List[str] = []
    source_url: Optional[str] = None
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    servings: Optional[int] = None


class RecipeUpdate(BaseModel):
    title: Optional[str] = None
    ingredients: Optional[List[str]] = None
    steps: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    dietary_tags: Optional[List[str]] = None
    allergens: Optional[List[str]] = None
    source_url: Optional[str] = None
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    servings: Optional[int] = None


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
    data = payload.model_dump()
    data["ingredients"] = _build_ingredients(data["ingredients"])
    recipe = Recipe(**data)
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
    data = payload.model_dump(exclude_unset=True)
    if "ingredients" in data:
        data["ingredients"] = _build_ingredients(data["ingredients"])
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
