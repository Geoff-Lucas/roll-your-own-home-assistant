from pathlib import Path
from typing import Annotated, Generator

from fastapi import Depends
from sqlalchemy import Engine, inspect
from sqlmodel import Session, SQLModel, create_engine

from .config import settings

settings.data_dir.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

# The first migration: the schema as it stood when migrations were introduced
# (see migrations/versions/). Databases created before then have tables but no
# alembic_version row; they're adopted at this revision rather than rebuilt.
BASELINE_REVISION = "851ee972b24c"


class MigrationError(RuntimeError):
    pass


def _alembic_config():
    from alembic.config import Config

    config = Config(str(_ALEMBIC_INI))
    config.attributes["running_in_app"] = True  # keeps migrations/env.py off the app's logging
    return config


def migrate(target: Engine = engine) -> None:
    """Bring the database schema up to date with the migrations.

    A database from before migrations existed is adopted first: any baseline
    table it lacks is created (an old dev database was missing two), then it's
    recorded as being at the baseline. That's only sound while the models still
    are the baseline; once later migrations exist, the models have moved on and
    an old database needs handling by hand, so this stops rather than guessing.
    """
    from alembic import command
    from alembic.script import ScriptDirectory

    from . import models  # noqa: F401  registers model classes with SQLModel metadata

    config = _alembic_config()
    with target.begin() as connection:
        config.attributes["connection"] = connection
        tables = set(inspect(connection).get_table_names())
        if tables and "alembic_version" not in tables:
            head = ScriptDirectory.from_config(config).get_current_head()
            if head != BASELINE_REVISION:
                raise MigrationError(
                    f"{settings.database_path} predates migrations and the schema has changed since "
                    f"(head is {head}, baseline {BASELINE_REVISION}). Bring it to the baseline schema by "
                    f"hand, then run: alembic stamp {BASELINE_REVISION}"
                )
            SQLModel.metadata.create_all(connection, checkfirst=True)
            command.stamp(config, BASELINE_REVISION)
        command.upgrade(config, "head")


def init_db() -> None:
    migrate(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
