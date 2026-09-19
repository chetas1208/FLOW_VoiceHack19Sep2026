"""`flow-migrate`: run schema migrations as a controlled release step (never at pod start)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from .db import make_engine
from .settings import Settings

MIGRATIONS = Path(__file__).parent / "migrations"
PG_LOCK_KEY = 7_204_117


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config("sqlite://")).get_current_head()


def current_revision(url: str) -> str | None:
    engine = make_engine(url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def upgrade(url: str, revision: str = "head") -> None:
    engine = make_engine(url)
    try:
        with engine.connect() as connection:
            if engine.dialect.name == "postgresql":
                connection.exec_driver_sql(f"SELECT pg_advisory_lock({PG_LOCK_KEY})")
            try:
                config = alembic_config(url)
                config.attributes["connection"] = connection
                command.upgrade(config, revision)
                connection.commit()
            finally:
                if engine.dialect.name == "postgresql":
                    connection.exec_driver_sql(f"SELECT pg_advisory_unlock({PG_LOCK_KEY})")
                    connection.commit()
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flow-migrate", description="Apply FLOW cloud database migrations")
    parser.add_argument("--check", action="store_true", help="exit 1 unless the database is at head")
    parser.add_argument("--sql", action="store_true", help="print offline SQL for head instead of applying")
    parser.add_argument("--revision", default="head")
    args = parser.parse_args(argv)
    url = Settings.from_env().database_url
    if not url:
        print("flow-migrate: DATABASE_URL is required", file=sys.stderr); return 2
    if args.sql:
        command.upgrade(alembic_config(url), "head", sql=True); return 0
    if args.check:
        current, head = current_revision(url), head_revision()
        print(f"current={current} head={head}")
        return 0 if current == head else 1
    upgrade(url, args.revision)
    print(f"flow-migrate: database at {current_revision(url)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
