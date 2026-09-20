import re
from typing import Optional

from recipe_scrapers import scrape_me

from ..models import Recipe
from .ingredient_parsing import parse_ingredient_line


def _safe(fn, default=None):
    """recipe-scrapers raises when a field isn't present on the source site
    (e.g. dietary_restrictions() on a site with no schema.org dietary data)
    rather than returning None — most fields are optional in practice."""
    try:
        return fn()
    except Exception:
        return default


def _parse_servings(yields_str: Optional[str]) -> Optional[int]:
    if not yields_str:
        return None
    match = re.search(r"\d+", yields_str)
    return int(match.group()) if match else None


def import_recipe_from_url(url: str) -> Recipe:
    """Scrape a recipe from its source URL into an unsaved Recipe row.

    Doesn't touch the database and doesn't download the image (see
    app/recipes/images.py — that only happens on first favorite) — this
    just builds the object; the caller commits it.
    """
    scraper = scrape_me(url)

    raw_ingredients = _safe(scraper.ingredients, default=[]) or []
    ingredients = [parse_ingredient_line(line) for line in raw_ingredients]

    return Recipe(
        title=_safe(scraper.title) or url,
        ingredients=ingredients,
        steps=_safe(scraper.instructions_list, default=[]) or [],
        dietary_tags=_safe(scraper.dietary_restrictions, default=[]) or [],
        source_url=url,
        source_image_url=_safe(scraper.image),
        prep_time_minutes=_safe(scraper.prep_time),
        cook_time_minutes=_safe(scraper.cook_time),
        servings=_parse_servings(_safe(scraper.yields)),
    )
