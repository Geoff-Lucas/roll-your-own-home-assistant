import logging

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlmodel import SQLModel, create_engine

from app import db, models

ALL_TABLES = {"account", "event", "location", "mealplan", "recipe", "recipefavorite", "timer"}


@pytest.fixture
def engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'test.db'}")


def tables(engine):
    return set(inspect(engine).get_table_names())


def version(engine):
    with engine.connect() as connection:
        return connection.execute(text("select version_num from alembic_version")).scalar_one()


def head():
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(db._alembic_config()).get_current_head()


def test_a_fresh_database_is_built_by_the_migrations(engine):
    db.migrate(engine)

    assert tables(engine) == ALL_TABLES | {"alembic_version"}
    assert version(engine) == head()


def test_the_migrations_and_the_models_agree(engine):
    # Fails when a model changes without a migration to match. Fix by running
    # `alembic revision --autogenerate -m "..."` from backend/ (see alembic.ini).
    db.migrate(engine)

    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), SQLModel.metadata)

    assert differences == []


def test_a_database_from_before_migrations_is_adopted_with_its_data_intact(engine):
    SQLModel.metadata.create_all(engine)  # how the app used to create it
    with engine.begin() as connection:
        connection.execute(text("insert into recipe (title, created_at) values ('Pancakes', '2026-09-01 00:00:00')"))

    db.migrate(engine)

    assert version(engine) == head()
    with engine.connect() as connection:
        assert connection.execute(text("select title from recipe")).scalars().all() == ["Pancakes"]


def test_an_old_database_missing_newer_tables_gets_them(engine):
    # The laptop's dev database predated the location and timer tables.
    SQLModel.metadata.create_all(engine, tables=[models.Account.__table__, models.Recipe.__table__])

    db.migrate(engine)

    assert tables(engine) == ALL_TABLES | {"alembic_version"}


def test_an_old_database_is_not_guessed_at_once_the_schema_has_moved_on(engine, monkeypatch):
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(db, "BASELINE_REVISION", "an-older-revision")

    with pytest.raises(db.MigrationError, match="predates migrations"):
        db.migrate(engine)

    assert "alembic_version" not in tables(engine)  # left untouched, not half-adopted


def test_migrating_twice_changes_nothing(engine):
    db.migrate(engine)
    db.migrate(engine)

    assert version(engine) == head()


def test_migrating_leaves_the_apps_logging_alone(engine):
    # Alembic's CLI setup would replace logging config and disable these.
    app_logger = logging.getLogger("app.some_module")
    app_logger.disabled = False

    db.migrate(engine)

    assert app_logger.disabled is False
