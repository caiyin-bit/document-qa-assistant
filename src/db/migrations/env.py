"""Alembic env: imports ORM metadata and runs online migrations.

Resolves the DB URL with this priority:
  1. DATABASE_URL env (used by docker-compose to point at `postgres` service)
  2. alembic.ini's sqlalchemy.url (host-mode dev default)

If the resolved URL uses asyncpg (postgresql+asyncpg://), we rewrite it
to the sync driver (postgresql://) — Alembic's engine_from_config is
sync; psycopg2-binary in runtime deps provides the driver.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from src.models.schemas import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolved_url() -> str:
    env_url = os.getenv("DATABASE_URL")
    url = env_url or config.get_main_option("sqlalchemy.url") or ""
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {}) or {}
    section["sqlalchemy.url"] = _resolved_url()
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=lambda *a, **kw: True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations not supported in this project")
else:
    run_migrations_online()
