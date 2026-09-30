"""Recipes saved on another computer, waiting on the NAS to be picked up.

The Windows "Recipe Importer" program (a separate project) writes each recipe
into an inbox folder on the NAS: a `.json` file, plus a photo beside it if the
recipe has one. deploy/pull-recipes-from-nas.sh mounts the share every fifteen
minutes and runs this module over that folder:

    python -m app.recipes.inbox /path/to/recipes/inbox

Every finished file moves to `imported/` (the recipe was added, or the kiosk
already had it) or `failed/` (with a `.error.txt` saying why), so a file is only
ever looked at once. The `.json` is written last by the sender, so a recipe is
never picked up without its photo.

The file holds what the kiosk's own "add recipe" call takes (ingredients as
plain lines: the same parser as everything else structures them here, so the
sending program doesn't need it), plus `format_version` and `image`.
"""

import argparse
import json
import logging
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import ValidationError
from sqlmodel import Session, select

from ..config import settings
from ..models import Recipe
from ..routers.recipes import RecipeCreate, _tidy

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class RecipeFile(RecipeCreate):
    format_version: int = FORMAT_VERSION
    # File name of the photo, in the same folder as the .json.
    image: Optional[str] = None


@dataclass
class Summary:
    added: list = field(default_factory=list)
    duplicates: list = field(default_factory=list)
    failed: list = field(default_factory=list)


def _already_have(session: Session, data: dict) -> Optional[Recipe]:
    """A recipe from the same page, or (typed in by hand, so no page) one with
    the same title and the same ingredients and steps. Catches a file being
    picked up twice after the NAS dropped out mid-move."""
    if data.get("source_url"):
        found = session.exec(select(Recipe).where(Recipe.source_url == data["source_url"])).first()
        if found is not None:
            return found
    title = data["title"].casefold()
    raw = [ingredient["raw_text"] for ingredient in data["ingredients"]]
    for recipe in session.exec(select(Recipe)).all():
        if (
            recipe.title.casefold() == title
            and [i.get("raw_text") for i in recipe.ingredients] == raw
            and recipe.steps == data["steps"]
        ):
            return recipe
    return None


def _image_source(folder: Path, name: Optional[str]) -> Optional[Path]:
    """The photo beside the .json, or None. Only the file name counts, so a
    name like "../../x" can't reach outside the inbox."""
    if not name:
        return None
    path = folder / Path(name).name
    if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.is_file():
        return None
    if path.stat().st_size > MAX_IMAGE_BYTES:
        return None
    return path


def _add_recipe(session: Session, folder: Path, package: RecipeFile) -> tuple[Recipe, bool]:
    """Returns the recipe and whether it was new."""
    data = _tidy(package.model_dump(exclude={"format_version", "image"}))
    existing = _already_have(session, data)
    if existing is not None:
        return existing, False

    recipe = Recipe(**data)
    session.add(recipe)
    session.flush()  # the id names the image file

    photo = _image_source(folder, package.image)
    if photo is not None:
        settings.recipe_images_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{recipe.id}{photo.suffix.lower()}"
        shutil.copyfile(photo, settings.recipe_images_dir / filename)
        recipe.image_path = f"/api/recipe-images/{filename}"
    elif package.image:
        logger.warning("%s: photo %r is missing, too big or not an image — saved without it", recipe.title, package.image)
    session.commit()
    session.refresh(recipe)
    return recipe, True


def _move(destination: Path, *paths: Path) -> None:
    destination.mkdir(exist_ok=True)
    for path in paths:
        if path.exists():
            # Replace, don't fail, when a same-named file was filed before.
            shutil.move(str(path), str(destination / path.name))


def process_inbox(inbox: Path, session: Session) -> Summary:
    summary = Summary()
    for path in sorted(inbox.glob("*.json")):
        photo_name = None
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict):
                raise ValueError("the file isn't a recipe (expected a JSON object)")
            if raw.get("format_version", FORMAT_VERSION) > FORMAT_VERSION:
                raise ValueError(f"made by a newer Recipe Importer (format {raw['format_version']}) — update the kiosk")
            package = RecipeFile(**raw)
            photo_name = package.image
            recipe, added = _add_recipe(session, inbox, package)
        except Exception as exc:
            session.rollback()
            reason = _describe(exc)
            logger.error("Couldn't import %s: %s", path.name, reason)
            summary.failed.append((path.name, reason))
            files = [path] + ([inbox / Path(photo_name).name] if photo_name else [])
            _move(inbox / "failed", *files)
            (inbox / "failed" / f"{path.stem}.error.txt").write_text(reason + "\n", encoding="utf-8")
            continue

        (summary.added if added else summary.duplicates).append(recipe.title)
        files = [path] + ([inbox / Path(photo_name).name] if photo_name else [])
        _move(inbox / "imported", *files)
    return summary


def _describe(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
    return str(exc) or exc.__class__.__name__


def main(argv: Optional[list] = None) -> int:
    from ..db import engine

    parser = argparse.ArgumentParser(description="Add the recipes waiting in a NAS inbox folder.")
    parser.add_argument("inbox", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.inbox.is_dir():
        print(f"No inbox at {args.inbox}", file=sys.stderr)
        return 1
    with Session(engine) as session:
        summary = process_inbox(args.inbox, session)
    print(
        f"Recipe inbox: {len(summary.added)} added, {len(summary.duplicates)} already on the kiosk, "
        f"{len(summary.failed)} failed"
    )
    for title in summary.added:
        print(f"  + {title}")
    for name, reason in summary.failed:
        print(f"  ! {name}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
