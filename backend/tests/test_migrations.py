import logging

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlmodel import SQLModel, create_engine

from app import db

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
    return ScriptDirectory.from_config(db._alembic_config()).get_current_head()


def event_delete_rule(engine):
    with engine.connect() as connection:
        (fk,) = connection.exec_driver_sql("pragma foreign_key_list('event')").fetchall()
    return fk[6]  # on_delete


def build_pre_migrations_database(engine):
    """A database as the app made it before migrations: the baseline schema,
    with no record of any migration having run (like the kiosk's was, and the
    copy kept at data/home_organizer.db.pre-migrations still is)."""
    config = db._alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, db.BASELINE_REVISION)
        connection.exec_driver_sql("drop table alembic_version")


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


def test_a_database_from_before_migrations_is_adopted_and_brought_up_to_date(engine):
    build_pre_migrations_database(engine)
    with engine.begin() as connection:
        connection.execute(text("insert into recipe (title, created_at) values ('Pancakes', '2026-09-01 00:00:00')"))
    assert event_delete_rule(engine) == "NO ACTION"

    db.migrate(engine)

    assert version(engine) == head()
    assert event_delete_rule(engine) == "CASCADE"  # later migrations ran too
    with engine.connect() as connection:
        assert connection.execute(text("select title from recipe")).scalars().all() == ["Pancakes"]


def test_an_old_database_missing_tables_is_refused_and_left_alone(engine):
    # The laptop's old dev database predated the location and timer tables.
    with engine.begin() as connection:
        connection.exec_driver_sql("create table account (id integer primary key)")
        connection.exec_driver_sql("create table recipe (id integer primary key)")

    with pytest.raises(db.MigrationError, match="lacks .*location.*timer"):
        db.migrate(engine)

    assert tables(engine) == {"account", "recipe"}


def test_a_migration_that_fails_partway_leaves_the_database_as_it_was(engine):
    build_pre_migrations_database(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("pragma foreign_keys=off")
        connection.execute(
            text("insert into event (account_id, uid, title, all_day, last_synced_at, reminder_dismissed) "
                 "values (99, 'orphan', 'Nobody''s', 0, '2026-09-01 00:00:00', 0)")
        )  # fmt: skip

    # The tables get rebuilt, then the integrity check finds the orphan and fails.
    with pytest.raises(db.MigrationError, match="don't exist"):
        db.migrate(engine)

    assert "alembic_version" not in tables(engine)  # never recorded as migrated
    assert event_delete_rule(engine) == "NO ACTION"  # the rebuild was undone too
    with engine.connect() as connection:
        assert connection.execute(text("select uid from event")).scalars().all() == ["orphan"]


def test_migrating_twice_changes_nothing(engine):
    db.migrate(engine)
    db.migrate(engine)

    assert version(engine) == head()


def test_foreign_keys_are_enforced_again_after_migrating(engine):
    db.migrate(engine)

    with engine.connect() as connection:
        assert connection.exec_driver_sql("pragma foreign_keys").scalar_one() == 1


def test_migrating_leaves_the_apps_logging_alone(engine):
    # Alembic's CLI setup would replace logging config and disable these.
    app_logger = logging.getLogger("app.some_module")
    app_logger.disabled = False

    db.migrate(engine)

    assert app_logger.disabled is False
