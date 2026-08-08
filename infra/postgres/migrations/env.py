"""Alembic runtime environment.

Sprint 0 Task 0.3 (`ZIP_14_IMPLEMENTATION_PREP/IMPLEMENTATION_ROADMAP.md` §6).

Resolves the database URL from the environment rather than `alembic.ini`, so no
connection string with a password is ever committed
(`IMPLEMENTATION_ROADMAP.md` §5 — no secrets committed).

`target_metadata` is intentionally `None`. The schema in
`ZIP_13_ENGINEERING_CONTRACTS/DATABASE_SCHEMA.md` §1-§18 is transcribed by hand
in each revision so the DDL can be diffed line-by-line against the contract
(Sprint 1 Task 1.6's Definition of Done). Autogenerate is therefore unusable by
design, and leaving metadata unbound makes that a hard failure rather than a
silently wrong diff.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# See module docstring: hand-written migrations only, never autogenerate.
target_metadata = None

# Defaults mirror docker-compose.yml's POSTGRES_* defaults so a fresh clone with
# no .env reaches the local compose Postgres unmodified. Task 0.6 documents these
# keys in .env.example.
_DEFAULTS = {
    "POSTGRES_USER": "businessscrapper",
    "POSTGRES_PASSWORD": "businessscrapper",
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "businessscrapper",
}


def get_url() -> str:
    """Return the SQLAlchemy URL, preferring an explicit DATABASE_URL.

    Falls back to assembling one from the POSTGRES_* variables that
    docker-compose.yml already reads, so host tooling and the containers agree
    on a single set of knobs.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    env = {key: os.environ.get(key) or default for key, default in _DEFAULTS.items()}
    return (
        "postgresql+psycopg://"
        f"{env['POSTGRES_USER']}:{env['POSTGRES_PASSWORD']}"
        f"@{env['POSTGRES_HOST']}:{env['POSTGRES_PORT']}/{env['POSTGRES_DB']}"
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (`alembic upgrade head --sql`)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and apply migrations."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
