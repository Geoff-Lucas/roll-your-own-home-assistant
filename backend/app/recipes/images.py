import logging
import mimetypes

import httpx

from ..config import settings
from ..models import Recipe

logger = logging.getLogger(__name__)


def ensure_recipe_image_downloaded(recipe: Recipe) -> None:
    """Download the recipe's source image to local storage, if not already
    done. Called when a recipe is first favorited — see PLAN.md Recipes
    section for why this is lazy rather than happening at import time (it
    keeps SSD storage bounded to recipes people actually use, not every
    recipe anyone ever pasted a URL for).

    Mutates recipe.image_path in place; the caller is responsible for
    adding/committing the session. Never raises — a failed download just
    means the recipe keeps using source_image_url for display instead.
    """
    if recipe.image_path or not recipe.source_image_url:
        return

    try:
        settings.recipe_images_dir.mkdir(parents=True, exist_ok=True)
        response = httpx.get(recipe.source_image_url, timeout=10, follow_redirects=True)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "").split(";")[0].strip()
        extension = mimetypes.guess_extension(content_type) or ".jpg"
        filename = f"{recipe.id}{extension}"
        (settings.recipe_images_dir / filename).write_bytes(response.content)

        recipe.image_path = f"/api/recipe-images/{filename}"
    except Exception:
        logger.exception("Failed to download image for recipe %s — keeping source_image_url only", recipe.id)
