"""Alembic environment: the URL comes from the caller, never from a checked-in ini file."""

from __future__ import annotations

from alembic import context
from sqlalchemy import pool

from services.flowcloud.db import make_engine, metadata

config = context.config
target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is None:
        engine = make_engine(config.get_main_option("sqlalchemy.url"))
        with engine.connect() as connection:
            _run(connection)
        engine.dispose()
    else:
        _run(connection)


def _run(connection) -> None:  # noqa: ANN001
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
