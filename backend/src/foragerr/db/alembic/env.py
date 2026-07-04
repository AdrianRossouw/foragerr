"""Alembic environment for foragerr — programmatic, online-only.

Invoked via ``foragerr.db.migrations.prepare_database`` (never a CLI
``alembic.ini`` workflow). Forward-only per FRG-DB-002: downgrade is not
supported anywhere in this chain.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config

if context.is_offline_mode():  # pragma: no cover - never used
    raise RuntimeError("foragerr migrations run online only")


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url")
    connectable = create_engine(url, poolclass=pool.NullPool)
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=None,
                render_as_batch=True,  # SQLite ALTER support for later revisions
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


run_migrations_online()
