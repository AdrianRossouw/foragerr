"""First-run default DDL provider seeding (FRG-DEP-013).

A fresh install should have the keyless search->grab->download pipeline
pre-configured and discoverable in Settings, but must NOT begin any outbound
acquisition on its own. So on the very first startup of an empty database the
system seeds exactly one **disabled** GetComics DDL indexer row (with its
automatic-search and RSS usage toggles off) and one **disabled** built-in DDL
download-client row (ddl-optin-seeding, 2026-07-09). Both use the model
defaults; no credential is needed. No search, scrape, grab, or download happens
until the operator deliberately enables the pair in Settings.

Once-per-database, never-resurrect semantics (mirroring the FRG-QUAL-002
default-format-profile seed) are enforced by a **persisted marker** — a single
row in the small ``app_state`` key/value table — NOT by a "tables are empty"
test. The marker is the gate:

- The forward-only migration (``0010_first_run_marker``) creates ``app_state``
  and, for an **established** database (one that already carries user config:
  any pre-existing ``indexers`` / ``download_clients`` / ``series`` row),
  pre-sets the marker WITHOUT inserting any provider. So an upgrade never gets
  rows injected. A genuinely fresh database gets no marker from the migration.
- At startup, AFTER ``import foragerr.ddl`` has populated the getcomics/ddl
  registry and after migrations, :func:`first_run_seed_startup_hook` runs. If
  the marker is unset it seeds the pair via the ordinary repo helpers (so
  settings validation and secret registration hold) and then sets the marker.
  If the marker is set it does nothing — a user who deletes a seeded row is
  never re-seeded on the next restart.

Crash-safety: seeding uses the repo helpers, which each commit their own write
session, so the row inserts and the marker set are not a single SQL
transaction. Idempotence is therefore guaranteed by two guards that make a
re-run a no-op regardless of where a crash landed: (1) the marker gate skips
the whole flow once set, and (2) a belt-and-suspenders reserved-name existence
check skips each insert whose row already exists. A crash after the inserts but
before the marker set leaves the rows present and the marker unset; the next
startup re-enters, the existence checks skip the (already-present) inserts, and
the marker is set — so seeding runs at most once per database and can never
double-insert.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:  # avoid importing FastAPI in the Alembic migration import path
    from fastapi import FastAPI

logger = logging.getLogger("foragerr.db.first_run")

#: The small meta/app-state key/value table that holds the first-run marker.
APP_STATE_TABLE = "app_state"
#: Marker key recording that first-run seeding has run for this database.
SEED_MARKER_KEY = "first_run_ddl_seed"
#: Marker value (presence of the row is what matters; the value is descriptive).
SEED_MARKER_VALUE = "done"

#: Reserved row name used as the belt-and-suspenders idempotency guard.
SEEDED_INDEXER_NAME = "GetComics"
SEEDED_CLIENT_NAME = "GetComics"

#: Registry implementation ids populated at ``import foragerr.ddl`` time.
GETCOMICS_IMPLEMENTATION = "getcomics"
DDL_CLIENT_IMPLEMENTATION = "ddl"


async def is_seed_complete(db) -> bool:
    """True iff the persisted first-run seed marker is set for this database."""
    async with db.read_session() as session:
        result = await session.execute(
            text(f"SELECT 1 FROM {APP_STATE_TABLE} WHERE key = :key"),
            {"key": SEED_MARKER_KEY},
        )
        return result.first() is not None


async def _set_seed_marker(db) -> None:
    """Set the marker idempotently (``WHERE NOT EXISTS`` on the reserved key)."""
    async with db.write_session() as session:
        await session.execute(
            text(
                f"INSERT INTO {APP_STATE_TABLE} (key, value) "
                "SELECT :key, :value "
                f"WHERE NOT EXISTS (SELECT 1 FROM {APP_STATE_TABLE} WHERE key = :key)"
            ),
            {"key": SEED_MARKER_KEY, "value": SEED_MARKER_VALUE},
        )


async def seed_first_run_defaults(db) -> None:
    """Seed the default keyless DDL pipeline once per database (FRG-DEP-013).

    No-op when the persisted marker is already set. Otherwise seeds one
    **disabled** GetComics indexer (automatic-search/RSS usage toggles off) and
    one **disabled** built-in DDL client through the ordinary repo helpers, then
    sets the marker — the pipeline is discoverable but performs no acquisition
    until the operator enables it (ddl-optin-seeding). Idempotent by the marker
    gate plus a reserved-name existence check (see the module docstring for
    crash-safety).
    """
    # Local imports: the getcomics/ddl registry is populated at
    # ``import foragerr.ddl`` time, and deferring these keeps this module cheap
    # to import from inside the Alembic migration (which only wants the
    # constants above).
    from foragerr.ddl.settings import GetComicsSettings
    from foragerr.downloads.repo import create_download_client, list_download_clients
    from foragerr.downloads.settings import BuiltinDdlSettings
    from foragerr.indexers.repo import create_indexer, list_indexers

    if await is_seed_complete(db):
        logger.debug("first-run seed: marker already set; nothing to seed")
        return

    seeded = False

    existing_indexers = await list_indexers(db)
    if not any(row.name == SEEDED_INDEXER_NAME for row in existing_indexers):
        await create_indexer(
            db,
            name=SEEDED_INDEXER_NAME,
            implementation=GETCOMICS_IMPLEMENTATION,
            settings=GetComicsSettings(),
            enabled=False,
            enable_rss=False,
            enable_auto=False,
        )
        seeded = True

    existing_clients = await list_download_clients(db)
    if not any(row.name == SEEDED_CLIENT_NAME for row in existing_clients):
        await create_download_client(
            db,
            name=SEEDED_CLIENT_NAME,
            implementation=DDL_CLIENT_IMPLEMENTATION,
            settings=BuiltinDdlSettings(),
            enabled=False,
        )
        seeded = True

    await _set_seed_marker(db)
    if seeded:
        logger.info(
            "first-run seed: created default GetComics indexer + built-in DDL "
            "client seeded disabled — enable in Settings to start acquiring"
        )


async def first_run_seed_startup_hook(app: "FastAPI") -> None:
    """Startup hook: seed the first-run defaults against the live database.

    Registered in ``create_app`` AFTER the db area's migration/engine startup
    hook (so ``app.state.db`` exists) and after ``import foragerr.ddl`` has
    populated the registry (so the getcomics/ddl implementations resolve).
    """
    await seed_first_run_defaults(app.state.db)


__all__ = [
    "APP_STATE_TABLE",
    "SEED_MARKER_KEY",
    "SEED_MARKER_VALUE",
    "SEEDED_INDEXER_NAME",
    "SEEDED_CLIENT_NAME",
    "is_seed_complete",
    "seed_first_run_defaults",
    "first_run_seed_startup_hook",
]
