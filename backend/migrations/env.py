"""Alembic's entry point, used both by the `alembic` command and by the app
itself at startup (app/db.py). The target schema is the SQLModel models.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

import app.models  # noqa: F401  registers every table on SQLModel.metadata
from app.config import settings

config = context.config

# Only when run as the `alembic` command. Inside the app, fileConfig would
# replace the app's logging setup and silence its loggers.
if config.config_file_name is not None and not config.attributes.get("running_in_app"):
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        # SQLite can't ALTER most things in place; batch mode rebuilds the
        # table instead, so column changes and drops work too.
        render_as_batch=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=config.get_main_option("sqlalchemy.url") or settings.database_url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:  # handed over by app/db.py
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    section = config.get_section(config.config_ini_section, {})
    section.setdefault("sqlalchemy.url", settings.database_url)
    engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
