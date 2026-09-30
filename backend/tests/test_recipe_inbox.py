"""Recipes waiting on the NAS: picked up once, structured like any other
recipe, and never added twice."""

import json

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import settings
from app.models import Recipe
from app.recipes import inbox as inbox_module


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(type(settings), "recipe_images_dir", property(lambda self: tmp_path / "images"))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    return inbox


def drop(folder, stem="2026-09-28_2130_chili_ab12", **fields):
    body = {"format_version": 1, "title": "Grandma's chili", "ingredients": ["2 cups flour"], "steps": ["Stir."], **fields}
    (folder / f"{stem}.json").write_text(json.dumps(body), encoding="utf-8")
    return stem


def test_a_recipe_is_added_structured_and_filed_away(session, folder):
    stem = drop(folder, source_url=" https://example.com/chili ", prep_time_minutes=10, tags=["Soup", "soup"])

    summary = inbox_module.process_inbox(folder, session)

    recipe = session.exec(select(Recipe)).one()
    assert summary.added == ["Grandma's chili"]
    assert recipe.ingredients[0] == {"raw_text": "2 cups flour", "name": "flour", "quantity_text": "2 cups"}
    assert recipe.source_url == "https://example.com/chili"
    assert recipe.tags == ["soup"]
    assert recipe.prep_time_minutes == 10
    assert not (folder / f"{stem}.json").exists()
    assert (folder / "imported" / f"{stem}.json").exists()


def test_the_photo_is_stored_under_the_recipes_id(session, folder, tmp_path):
    stem = drop(folder, image="chili.png")
    (folder / "chili.png").write_bytes(b"\x89PNG fake")

    inbox_module.process_inbox(folder, session)

    recipe = session.exec(select(Recipe)).one()
    assert recipe.image_path == f"/api/recipe-images/{recipe.id}.png"
    assert (tmp_path / "images" / f"{recipe.id}.png").read_bytes() == b"\x89PNG fake"
    assert (folder / "imported" / "chili.png").exists()
    assert not (folder / "chili.png").exists()
    assert (folder / "imported" / f"{stem}.json").exists()


def test_a_missing_or_odd_photo_still_saves_the_recipe(session, folder):
    drop(folder, stem="a", image="gone.jpg")
    drop(folder, stem="b", title="Other", image="../../etc/passwd")
    (folder / "notes.txt").write_text("not an image")

    summary = inbox_module.process_inbox(folder, session)

    assert len(summary.added) == 2
    assert all(recipe.image_path is None for recipe in session.exec(select(Recipe)).all())


def test_source_image_url_is_kept_for_a_later_download(session, folder):
    drop(folder, source_image_url="https://example.com/chili.jpg")

    inbox_module.process_inbox(folder, session)

    recipe = session.exec(select(Recipe)).one()
    assert recipe.source_image_url == "https://example.com/chili.jpg"
    assert recipe.image_path is None


def test_the_same_page_twice_is_added_once(session, folder):
    drop(folder, stem="a", source_url="https://example.com/chili")
    drop(folder, stem="b", source_url="https://example.com/chili", title="Chili again")

    summary = inbox_module.process_inbox(folder, session)

    assert len(session.exec(select(Recipe)).all()) == 1
    assert summary.duplicates == ["Grandma's chili"]
    assert (folder / "imported" / "b.json").exists()


def test_a_hand_typed_recipe_picked_up_twice_is_added_once(session, folder):
    drop(folder, stem="a")
    inbox_module.process_inbox(folder, session)
    drop(folder, stem="a-again", title="GRANDMA'S CHILI")

    summary = inbox_module.process_inbox(folder, session)

    assert len(session.exec(select(Recipe)).all()) == 1
    assert summary.duplicates == ["Grandma's chili"]


def test_a_different_recipe_with_the_same_title_is_kept(session, folder):
    drop(folder, stem="a")
    drop(folder, stem="b", ingredients=["1 lb beef"])

    inbox_module.process_inbox(folder, session)

    assert len(session.exec(select(Recipe)).all()) == 2


@pytest.mark.parametrize(
    "content, reason",
    [
        ("{not json", "Expecting"),
        ("[1, 2]", "expected a JSON object"),
        (json.dumps({"format_version": 1}), "title"),
        (json.dumps({"format_version": 9, "title": "x"}), "newer Recipe Importer"),
        (json.dumps({"title": "x", "servings": 0}), "servings"),
    ],
)
def test_a_bad_file_is_set_aside_with_the_reason(session, folder, content, reason):
    (folder / "bad.json").write_text(content, encoding="utf-8")
    drop(folder, stem="good")

    summary = inbox_module.process_inbox(folder, session)

    assert summary.added == ["Grandma's chili"]  # one bad file doesn't stop the rest
    assert len(summary.failed) == 1
    assert reason in (folder / "failed" / "bad.error.txt").read_text()
    assert (folder / "failed" / "bad.json").exists()
    assert not (folder / "bad.json").exists()


def test_an_empty_inbox_is_fine(session, folder):
    summary = inbox_module.process_inbox(folder, session)

    assert (summary.added, summary.duplicates, summary.failed) == ([], [], [])
