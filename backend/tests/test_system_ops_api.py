"""API + scheduler wiring for m2-ops-health-backups (area 2): the extended
``GET /api/v1/system/status``, the health-warnings/per-component transport
(``GET /api/v1/health`` / ``GET /api/v1/system/health``), the scheduled-task
list + force-run (``GET``/``POST /api/v1/system/task*``), the
``backup-database`` task registration, and the startup-hook ordering that
wires area 1's restore-marker / quick_check hooks into ``app.py``
(FRG-API-014, FRG-NFR-011, FRG-DB-009).

Most tests here drive the app's lifespan directly on the CURRENT event loop
(``async with app.router.lifespan_context(app):``) plus an ASGI-transport
``httpx.AsyncClient``, rather than ``TestClient``'s separate portal thread —
this lets a test freely mix HTTP calls with direct ``app.state`` access (e.g.
seeding an indexer / forcing a provider into back-off) on one loop without
cross-event-loop errors against the async engine. The startup-hook ordering
tests are plain sync tests using ``TestClient``, matching ``test_app.py``'s
existing style, since they only need to observe call order via monkeypatched
spies.
"""

from __future__ import annotations

import datetime as dt
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.config import Settings
from foragerr.db import DB_FILENAME
from foragerr.db.backup import BACKUPS_DIRNAME
from foragerr.indexers.models import IndexerRow
from foragerr.providers.backoff import PROVIDER_INDEXER, ProviderBackoff


def _settings(tmp_path: Path, **overrides) -> Settings:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return Settings(config_dir=cfg, **overrides)


@asynccontextmanager
async def running_app(settings: Settings):
    """A fully started app (lifespan driven on the CURRENT loop) plus an
    ASGI-transport client — yields ``(app, client)``."""
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield app, client


async def _add_indexer(app, name: str = "DogNZB", settings_json: str = "{}") -> int:
    async with app.state.db.write_session() as session:
        row = IndexerRow(
            name=name,
            implementation="newznab",
            protocol="usenet",
            priority=25,
            enabled=True,
            enable_rss=True,
            enable_auto=True,
            enable_interactive=True,
            settings=settings_json,
            added_at=dt.datetime(2026, 1, 1),
        )
        session.add(row)
        await session.flush()
        return row.id


# --- GET /api/v1/system/status (FRG-API-014) --------------------------------


@pytest.mark.req("FRG-API-014")
async def test_system_status_extended_with_runtime_paths_and_no_secret(tmp_path):
    settings = _settings(tmp_path)
    secret = "SUPER-SECRET-INDEXER-KEY-42"
    async with running_app(settings) as (app, client):
        await _add_indexer(app, settings_json=json.dumps({"apikey": secret}))
        response = await client.get("/api/v1/system/status")

    assert response.status_code == 200
    body = response.json()
    # The original trio stays byte-for-byte (FRG-DEP-010).
    assert {"version", "commit", "build_date"} <= body.keys()
    # The delta's additive runtime + managed-path fields.
    for field in (
        "config_dir",
        "db_path",
        "backups_dir",
        "root_folder_count",
        "uptime_seconds",
        "python_version",
        "os",
    ):
        assert field in body, field
    assert body["config_dir"] == str(settings.config_dir)
    assert body["db_path"] == str(settings.config_dir / DB_FILENAME)
    assert body["backups_dir"] == str(settings.config_dir / BACKUPS_DIRNAME)
    assert body["root_folder_count"] == 0
    assert body["uptime_seconds"] >= 0
    assert body["python_version"]
    assert body["os"]
    # No secret leak anywhere in the response.
    assert secret not in response.text


# --- GET /api/v1/health (FRG-API-014 / FRG-NFR-011) -------------------------


@pytest.mark.req("FRG-API-014")
@pytest.mark.req("FRG-NFR-011")
async def test_health_warnings_lists_actionable_item_with_camelcase_hint(tmp_path):
    settings = _settings(tmp_path)
    async with running_app(settings) as (app, client):
        indexer_id = await _add_indexer(app)
        await ProviderBackoff(app.state.db).record_failure(
            PROVIDER_INDEXER, indexer_id, reason="auth failed"
        )
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list) and items
    item = next(i for i in items if i["source"] == f"indexer:{indexer_id}")
    assert item["type"] in ("warning", "error")
    # remediationHint is camelCase verbatim (design decision 5) — the alias,
    # not the Python field name, must be on the wire.
    assert "remediationHint" in item
    assert "remediation_hint" not in item
    assert item["remediationHint"]


@pytest.mark.req("FRG-API-014")
async def test_health_warnings_empty_when_service_reports_no_warnings(
    tmp_path, monkeypatch
):
    """A fully-healthy system returns an empty warnings list — proven at the
    transport layer via a stub service (the health-aggregation logic itself,
    including the non-ok-subset invariant, is area 1's test_health_service.py)."""
    import foragerr.api.system as system_module

    class _StubHealthService:
        async def warnings(self):
            return []

    monkeypatch.setattr(
        system_module, "health_service_from_app", lambda app: _StubHealthService()
    )

    settings = _settings(tmp_path)
    async with running_app(settings) as (_app, client):
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == []


# --- GET /api/v1/system/health (FRG-NFR-011) --------------------------------


@pytest.mark.req("FRG-NFR-011")
async def test_system_health_every_component_represented_with_frontend_shape(
    tmp_path,
):
    settings = _settings(tmp_path)
    async with running_app(settings) as (_app, client):
        response = await client.get("/api/v1/system/health")

    assert response.status_code == 200
    components = response.json()
    assert components  # comicvine/scheduler/database/disk-space always present
    ids = {c["component"] for c in components}
    assert {"comicvine", "scheduler", "database", "disk-space"} <= ids

    for c in components:
        assert c["state"] in ("ok", "degraded", "error")
        # Matches the frontend's COMMITTED SystemHealthComponent type exactly:
        # no `kind`/`label`/`remediation` (the domain ComponentHealth's extra
        # fields) leak onto the wire.
        assert set(c.keys()) == {
            "component",
            "state",
            "message",
            "last_success",
            "last_failure",
            "disabled_until",
        }

    scheduler_comp = next(c for c in components if c["component"] == "scheduler")
    assert scheduler_comp["state"] == "ok"  # deterministic: status() succeeds


# --- GET /api/v1/system/task + POST force-run (FRG-API-014 / FRG-DB-009) ---


@pytest.mark.req("FRG-API-014")
@pytest.mark.req("FRG-DB-009")
async def test_system_task_list_includes_backup_database(tmp_path):
    settings = _settings(tmp_path, db_backup_interval_seconds=7200)
    async with running_app(settings) as (_app, client):
        response = await client.get("/api/v1/system/task")

    assert response.status_code == 200
    tasks = {t["name"]: t for t in response.json()}
    assert "housekeeping" in tasks  # pre-existing builtin task still lists
    task = tasks["backup-database"]
    assert task["command_name"] == "backup-database"
    assert task["interval_seconds"] == 7200
    assert task["label"]  # a non-empty display label


@pytest.mark.req("FRG-API-014")
@pytest.mark.req("FRG-DB-009")
async def test_force_run_backup_database_returns_command_and_resets_timer(tmp_path):
    settings = _settings(tmp_path)
    async with running_app(settings) as (_app, client):
        response = await client.post("/api/v1/system/task/backup-database")
        assert response.status_code == 202
        body = response.json()
        assert body["name"] == "backup-database"
        assert body["id"] > 0
        assert body["status"] in ("queued", "started", "completed")

        tasks_response = await client.get("/api/v1/system/task")

    tasks = {t["name"]: t for t in tasks_response.json()}
    assert tasks["backup-database"]["last_run"] is not None  # timer reset


@pytest.mark.req("FRG-API-014")
async def test_force_run_unknown_task_returns_404(tmp_path):
    settings = _settings(tmp_path)
    async with running_app(settings) as (_app, client):
        response = await client.post("/api/v1/system/task/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert "message" in body
    assert "errors" in body


# --- Startup hook ordering (FRG-DB-010 / FRG-DB-012) ------------------------
#
# Plain sync tests using TestClient (not the async fixture above): they only
# need to observe call order via monkeypatched spies around the REAL
# functions, matching test_app.py's existing lifespan-ordering style.


@pytest.mark.req("FRG-DB-010")
def test_restore_marker_hook_runs_before_database_engine_opens(tmp_path, monkeypatch):
    from foragerr.db.restore import apply_restore_marker as real_apply_restore_marker

    calls: list[str] = []

    def spy_restore(config_dir):
        calls.append("restore")
        return real_apply_restore_marker(config_dir)

    from foragerr.db import prepare_database as real_prepare_database

    def spy_prepare(config_dir, retention=3):
        calls.append("prepare_database")
        return real_prepare_database(config_dir, retention=retention)

    monkeypatch.setattr("foragerr.db.backup_command.apply_restore_marker", spy_restore)
    monkeypatch.setattr("foragerr.db.prepare_database", spy_prepare)

    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app):
        pass

    assert calls, "expected the restore-marker hook to run"
    assert calls.index("restore") < calls.index("prepare_database")


@pytest.mark.req("FRG-DB-012")
def test_quick_check_hook_runs_after_database_prepared(tmp_path, monkeypatch):
    from foragerr.db import prepare_database as real_prepare_database
    from foragerr.db.integrity import run_quick_check as real_run_quick_check

    calls: list[str] = []

    def spy_prepare(config_dir, retention=3):
        calls.append("prepare_database")
        return real_prepare_database(config_dir, retention=retention)

    def spy_quick_check(db_path):
        calls.append("quick_check")
        return real_run_quick_check(db_path)

    monkeypatch.setattr("foragerr.db.prepare_database", spy_prepare)
    monkeypatch.setattr("foragerr.db.backup_command.run_quick_check", spy_quick_check)

    settings = _settings(tmp_path)
    app = create_app(settings)
    with TestClient(app):
        pass

    assert calls, "expected the quick_check hook to run"
    assert calls.index("prepare_database") < calls.index("quick_check")
