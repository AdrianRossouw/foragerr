"""FRG-DEP-013 — first-run default DDL provider seeding.

A fresh install seeds exactly one enabled GetComics indexer and one enabled
built-in DDL client (a keyless pipeline), gated by a persisted marker so an
upgrade never gets rows injected and a user-deleted seeded row is never
resurrected. See ``foragerr.db.first_run``.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from alembic import command
from fastapi.testclient import TestClient

# The getcomics indexer implementation is registered at ``import foragerr.ddl``
# time; the built-in ``ddl`` download-client implementation at
# ``import foragerr.downloads`` time. Both must be present for the repo helpers
# to resolve the implementations the seed uses.
import foragerr.ddl  # noqa: F401 — registers the getcomics/ddl implementations
import foragerr.downloads  # noqa: F401 — registers the ddl download-client impl
from foragerr.app import create_app
from foragerr.config import Settings
from foragerr.db import DB_FILENAME, Database, prepare_database
from foragerr.db.first_run import (
    APP_STATE_TABLE,
    DDL_CLIENT_IMPLEMENTATION,
    GETCOMICS_IMPLEMENTATION,
    SEED_MARKER_KEY,
    SEEDED_INDEXER_NAME,
    is_seed_complete,
    seed_first_run_defaults,
)
from foragerr.db.migrations import ALEMBIC_DIR, _make_config
from foragerr.downloads.repo import (
    create_download_client,
    delete_download_client,
    list_download_clients,
)
from foragerr.downloads.settings import BuiltinDdlSettings
from foragerr.indexers.repo import (
    create_indexer,
    delete_indexer,
    list_indexers,
)
from foragerr.ddl.settings import GetComicsSettings


# --------------------------------------------------------------------------- #
# Marker migration (0010): fresh leaves it unset, established pre-sets it       #
# --------------------------------------------------------------------------- #


def _marker_rows(db_path) -> list[tuple[str, str]]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            f"SELECT key, value FROM {APP_STATE_TABLE} WHERE key = ?",
            (SEED_MARKER_KEY,),
        ).fetchall()


@pytest.mark.req("FRG-DEP-013")
def test_fresh_db_migration_leaves_marker_unset(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0010_first_run_marker" in result.applied
    # The app_state table exists but carries NO first-run marker: a genuinely
    # fresh (empty) database is seeded by the startup step, not the migration.
    assert _marker_rows(db_path) == []


@pytest.mark.req("FRG-DEP-013")
def test_established_db_migration_presets_marker_without_injection(tmp_path):
    """A DB that already carries user config is marked seeded WITHOUT any
    provider being injected (the upgrade-safety heuristic)."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    db_path = cfg / DB_FILENAME
    alembic_cfg = _make_config(db_path, ALEMBIC_DIR)

    # Migrate to the revision just before the marker migration...
    command.upgrade(alembic_cfg, "0009_history_created_at_index")
    # ...then plant a pre-existing indexer row so the DB looks "established".
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO indexers "
            "(name, implementation, protocol, priority, enabled, enable_rss, "
            "enable_auto, enable_interactive, settings, added_at) "
            "VALUES ('DogNZB', 'newznab', 'usenet', 25, 1, 1, 1, 1, '{}', "
            "'2026-01-01T00:00:00')"
        )
        conn.commit()

    # Now apply the marker migration.
    command.upgrade(alembic_cfg, "0010_first_run_marker")

    # The marker is pre-set...
    assert _marker_rows(db_path) == [(SEED_MARKER_KEY, "done")]
    # ...and NO GetComics/DDL provider was injected — only the row we planted.
    with sqlite3.connect(db_path) as conn:
        impls = [
            r[0] for r in conn.execute("SELECT implementation FROM indexers")
        ]
        client_count = conn.execute(
            "SELECT COUNT(*) FROM download_clients"
        ).fetchone()[0]
    assert impls == ["newznab"]
    assert client_count == 0


# --------------------------------------------------------------------------- #
# Seeding logic against a fresh head-revision DB (db fixture = empty, unset)    #
# --------------------------------------------------------------------------- #


def _getcomics_indexers(rows):
    return [r for r in rows if r.implementation == GETCOMICS_IMPLEMENTATION]


def _ddl_clients(rows):
    return [r for r in rows if r.implementation == DDL_CLIENT_IMPLEMENTATION]


@pytest.mark.req("FRG-DEP-013")
async def test_fresh_start_seeds_enabled_getcomics_and_ddl_and_sets_marker(db):
    assert await is_seed_complete(db) is False  # fresh DB: marker unset

    await seed_first_run_defaults(db)

    indexers = _getcomics_indexers(await list_indexers(db))
    clients = _ddl_clients(await list_download_clients(db))

    assert len(indexers) == 1
    idx = indexers[0]
    assert idx.name == SEEDED_INDEXER_NAME
    assert idx.protocol == "ddl"
    assert idx.enabled is True
    assert json.loads(idx.settings) == {
        "base_url": "https://getcomics.org",
        "min_interval_seconds": 15,
        "max_pages": 3,
    }

    assert len(clients) == 1
    client = clients[0]
    assert client.protocol == "ddl"
    assert client.enabled is True
    assert json.loads(client.settings) == {
        "host_priority": "main,mirror,pixeldrain,mediafire,mega",
        "prefer_upscaled": True,
    }

    assert await is_seed_complete(db) is True


@pytest.mark.req("FRG-DEP-013")
async def test_deleted_seeded_row_not_resurrected_on_restart(db):
    await seed_first_run_defaults(db)
    seeded = _getcomics_indexers(await list_indexers(db))[0]

    # User deletes the seeded indexer, then the app restarts (seed runs again).
    assert await delete_indexer(db, seeded.id) is True
    await seed_first_run_defaults(db)

    # The marker gate — not a table-empty test — means it is NOT recreated.
    assert _getcomics_indexers(await list_indexers(db)) == []
    assert await is_seed_complete(db) is True


@pytest.mark.req("FRG-DEP-013")
async def test_deleted_seeded_client_not_resurrected_on_restart(db):
    await seed_first_run_defaults(db)
    seeded = _ddl_clients(await list_download_clients(db))[0]

    assert await delete_download_client(db, seeded.id) is True
    await seed_first_run_defaults(db)

    assert _ddl_clients(await list_download_clients(db)) == []


@pytest.mark.req("FRG-DEP-013")
async def test_double_startup_is_idempotent(db):
    await seed_first_run_defaults(db)
    await seed_first_run_defaults(db)  # second startup: no-op via the marker

    assert len(_getcomics_indexers(await list_indexers(db))) == 1
    assert len(_ddl_clients(await list_download_clients(db))) == 1


@pytest.mark.req("FRG-DEP-013")
async def test_newznab_and_sabnzbd_are_never_seeded(db):
    await seed_first_run_defaults(db)

    indexers = await list_indexers(db)
    clients = await list_download_clients(db)
    assert all(r.implementation == GETCOMICS_IMPLEMENTATION for r in indexers)
    assert all(r.implementation == DDL_CLIENT_IMPLEMENTATION for r in clients)
    assert not any(r.implementation == "newznab" for r in indexers)
    assert not any(r.implementation == "sabnzbd" for r in clients)


@pytest.mark.req("FRG-DEP-013")
async def test_crash_before_marker_does_not_double_seed(db):
    """Crash-safety: if a prior boot inserted the rows but crashed before the
    marker was set (marker still unset), the next startup must NOT double-seed —
    the reserved-name existence guard skips the inserts and only sets the
    marker."""
    # Simulate the partial state: seeded rows present, marker unset.
    await create_indexer(
        db,
        name=SEEDED_INDEXER_NAME,
        implementation=GETCOMICS_IMPLEMENTATION,
        settings=GetComicsSettings(),
        enabled=True,
    )
    await create_download_client(
        db,
        name=SEEDED_INDEXER_NAME,
        implementation=DDL_CLIENT_IMPLEMENTATION,
        settings=BuiltinDdlSettings(),
        enabled=True,
    )
    assert await is_seed_complete(db) is False

    await seed_first_run_defaults(db)

    # No duplicates, and the marker is now set.
    assert len(_getcomics_indexers(await list_indexers(db))) == 1
    assert len(_ddl_clients(await list_download_clients(db))) == 1
    assert await is_seed_complete(db) is True


@pytest.mark.req("FRG-DEP-013")
async def test_crash_with_only_indexer_present_seeds_just_the_client(db):
    """Asymmetric partial state: a prior boot inserted the indexer but crashed
    before the client (marker still unset). The next startup inserts ONLY the
    missing client — the per-row existence guards are independent — with no
    duplicate indexer, and sets the marker."""
    await create_indexer(
        db,
        name=SEEDED_INDEXER_NAME,
        implementation=GETCOMICS_IMPLEMENTATION,
        settings=GetComicsSettings(),
        enabled=True,
    )
    assert _ddl_clients(await list_download_clients(db)) == []  # client absent
    assert await is_seed_complete(db) is False

    await seed_first_run_defaults(db)

    # The missing client was created; the pre-existing indexer was not duplicated.
    assert len(_getcomics_indexers(await list_indexers(db))) == 1
    assert len(_ddl_clients(await list_download_clients(db))) == 1
    assert await is_seed_complete(db) is True


@pytest.mark.req("FRG-DEP-013")
async def test_crash_with_only_client_present_seeds_just_the_indexer(db):
    """The reverse asymmetric state: the client is present but the indexer is
    absent. The next startup inserts ONLY the missing indexer, no duplicate
    client, and sets the marker."""
    await create_download_client(
        db,
        name=SEEDED_INDEXER_NAME,
        implementation=DDL_CLIENT_IMPLEMENTATION,
        settings=BuiltinDdlSettings(),
        enabled=True,
    )
    assert _getcomics_indexers(await list_indexers(db)) == []  # indexer absent
    assert await is_seed_complete(db) is False

    await seed_first_run_defaults(db)

    assert len(_getcomics_indexers(await list_indexers(db))) == 1
    assert len(_ddl_clients(await list_download_clients(db))) == 1
    assert await is_seed_complete(db) is True


# --------------------------------------------------------------------------- #
# End-to-end: the startup hook wired into create_app's lifespan                 #
# --------------------------------------------------------------------------- #


@pytest.mark.req("FRG-DEP-013")
def test_startup_hook_seeds_on_first_run(tmp_path):
    path = tmp_path / "cfg"
    path.mkdir()
    app = create_app(Settings(config_dir=path))

    with TestClient(app) as client:  # entering the context runs the lifespan
        indexers = client.get("/api/v1/indexer").json()
        clients = client.get("/api/v1/downloadclient").json()

    getcomics = [i for i in indexers if i["implementation"] == "getcomics"]
    ddl = [c for c in clients if c["implementation"] == "ddl"]
    assert len(getcomics) == 1
    assert getcomics[0]["enabled"] is True
    assert getcomics[0]["protocol"] == "ddl"
    assert len(ddl) == 1
    assert ddl[0]["enabled"] is True
    assert ddl[0]["protocol"] == "ddl"


@pytest.mark.req("FRG-DEP-013")
def test_restart_after_delete_does_not_resurrect_end_to_end(tmp_path):
    path = tmp_path / "cfg"
    path.mkdir()

    # First run: seeds the pair, then the user deletes the GetComics indexer.
    app1 = create_app(Settings(config_dir=path))
    with TestClient(app1) as client:
        seeded = client.get("/api/v1/indexer").json()
        target = next(i for i in seeded if i["implementation"] == "getcomics")
        assert client.delete(f"/api/v1/indexer/{target['id']}").status_code == 204

    # Second run against the SAME config dir: the marker is set, so nothing is
    # re-seeded.
    app2 = create_app(Settings(config_dir=path))
    with TestClient(app2) as client:
        after = client.get("/api/v1/indexer").json()
    assert [i for i in after if i["implementation"] == "getcomics"] == []


@pytest.mark.req("FRG-DEP-013")
async def test_startup_hook_skips_established_database(tmp_path):
    """The migration pre-set + startup hook together mean an established DB is
    never injected: pre-set the marker, plant NO providers, run the seed hook,
    and confirm nothing is created."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    db_path = cfg / DB_FILENAME
    alembic_cfg = _make_config(db_path, ALEMBIC_DIR)
    command.upgrade(alembic_cfg, "0009_history_created_at_index")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO indexers "
            "(name, implementation, protocol, priority, enabled, enable_rss, "
            "enable_auto, enable_interactive, settings, added_at) "
            "VALUES ('DogNZB', 'newznab', 'usenet', 25, 1, 1, 1, 1, '{}', "
            "'2026-01-01T00:00:00')"
        )
        conn.commit()
    command.upgrade(alembic_cfg, "0010_first_run_marker")

    database = Database(db_path=db_path)
    try:
        assert await is_seed_complete(database) is True
        await seed_first_run_defaults(database)
        assert _getcomics_indexers(await list_indexers(database)) == []
        assert _ddl_clients(await list_download_clients(database)) == []
    finally:
        await database.close()
