import sqlite3
from pathlib import Path
from typing import Annotated, Generator

from fastapi import Depends
from sqlalchemy import Engine, event, inspect
from sqlmodel import Session, create_engine

from .config import settings

settings.data_dir.mkdir(parents=True, exist_ok=True)


@event.listens_for(Engine, "connect")
def _enforce_foreign_keys(dbapi_connection, _record) -> None:
    """SQLite ignores foreign keys unless each connection turns them on. Off,
    deleting an account left its events behind (still on the calendar and in
    reminders). Every engine, the tests' included, so they behave like the app."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

# The first migration: the schema as it stood when migrations were introduced
# (see migrations/versions/). Databases created before then have tables but no
# alembic_version row; they're adopted at this revision rather than rebuilt.
BASELINE_REVISION = "851ee972b24c"
BASELINE_TABLES = {"account", "event", "location", "mealplan", "recipe", "recipefavorite", "timer"}


class MigrationError(RuntimeError):
    pass


def _alembic_config():
    from alembic.config import Config

    config = Config(str(_ALEMBIC_INI))
    config.attributes["running_in_app"] = True  # keeps migrations/env.py off the app's logging
    return config


def migrate(target: Engine = engine) -> None:
    """Bring the database schema up to date with the migrations.

    A database from before migrations existed (such as the copy kept at
    data/home_organizer.db.pre-migrations) is adopted: recorded as being at the
    baseline, then migrated forward like any other. It must have every baseline
    table; one that doesn't (an old dev database lacked two) is refused rather
    than guessed at, since creating them from today's models could clash with
    later migrations.

    It all happens in one transaction, so a migration that fails partway leaves
    the database exactly as it was. That takes an explicit BEGIN: Python's
    sqlite3 driver only opens a transaction on its own before an INSERT or
    UPDATE, so the table-creating statements a migration starts with would
    otherwise commit one at a time (the partial-failure test in
    tests/test_migrations.py fails without it). Foreign-key checks are off
    meanwhile, as SQLite advises for schema changes (rebuilding a table would
    trip its own references), and the whole database is checked before the commit.
    """
    from alembic import command

    config = _alembic_config()
    with target.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")  # only takes effect outside a transaction
        connection.exec_driver_sql("BEGIN")
        try:
            config.attributes["connection"] = connection
            tables = set(inspect(connection).get_table_names())
            if tables and "alembic_version" not in tables:
                missing = BASELINE_TABLES - tables
                if missing:
                    raise MigrationError(
                        f"{settings.database_path} predates migrations and lacks {', '.join(sorted(missing))}; "
                        f"create them to match the baseline migration, then run: alembic stamp {BASELINE_REVISION}"
                    )
                command.stamp(config, BASELINE_REVISION)
            command.upgrade(config, "head")
            broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if broken:
                raise MigrationError(f"Rows point at records that don't exist after migrating: {broken[:5]}")
            connection.exec_driver_sql("COMMIT")
        except BaseException:
            connection.exec_driver_sql("ROLLBACK")
            raise
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")


def init_db() -> None:
    migrate(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
