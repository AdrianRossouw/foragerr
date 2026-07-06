"""The health-aggregation service: per-component view + warnings subset
(FRG-NFR-011)."""

from __future__ import annotations

import datetime as dt

import pytest

from foragerr.config import Settings
from foragerr.db import DB_FILENAME
from foragerr.db.backup import write_scheduled_backup
from foragerr.downloads.models import DownloadClientRow
from foragerr.health import HealthService
from foragerr.health.state import record_integrity, reset_integrity
from foragerr.indexers.models import IndexerRow
from foragerr.library.models import RootFolderRow
from foragerr.metadata import ratelimit
from foragerr.providers.backoff import PROVIDER_INDEXER, ProviderBackoff


@pytest.fixture(autouse=True)
def _isolate_health():
    reset_integrity()
    ratelimit.reset_gate()
    yield
    reset_integrity()
    ratelimit.reset_gate()


def _settings(db) -> Settings:
    return Settings(config_dir=db.db_path.parent)


class _StubScheduler:
    async def status(self):
        return []


def _service(db, **kw) -> HealthService:
    return HealthService(db, _settings(db), scheduler=_StubScheduler(), **kw)


async def _add_indexer(db, name: str = "DogNZB") -> int:
    async with db.write_session() as session:
        row = IndexerRow(
            name=name,
            implementation="newznab",
            protocol="usenet",
            priority=25,
            enabled=True,
            enable_rss=True,
            enable_auto=True,
            enable_interactive=True,
            settings="{}",
            added_at=dt.datetime(2026, 1, 1),
        )
        session.add(row)
        await session.flush()
        return row.id


async def _add_client(db, *, name: str, implementation: str) -> int:
    async with db.write_session() as session:
        row = DownloadClientRow(
            name=name,
            implementation=implementation,
            protocol="ddl" if implementation == "ddl" else "usenet",
            priority=25,
            enabled=True,
            remove_completed_downloads=True,
            settings="{}",
            added_at=dt.datetime(2026, 1, 1),
        )
        session.add(row)
        await session.flush()
        return row.id


def _by_component(components):
    return {c.component: c for c in components}


@pytest.mark.req("FRG-NFR-011")
async def test_indexer_backoff_shows_degraded_then_recovers(db):
    indexer_id = await _add_indexer(db)
    backoff = ProviderBackoff(db)
    await backoff.record_failure(PROVIDER_INDEXER, indexer_id, reason="auth failed")

    service = _service(db)
    comp = _by_component(await service.component_view())[f"indexer:{indexer_id}"]
    assert comp.state == "degraded"
    assert comp.disabled_until is not None  # its disabled-until time
    assert comp.last_failure is not None  # last-failure time
    warning_sources = {w.source for w in await service.warnings()}
    assert f"indexer:{indexer_id}" in warning_sources

    # Recovery clears it on the next poll without a restart.
    await backoff.record_success(PROVIDER_INDEXER, indexer_id)
    comp2 = _by_component(await service.component_view())[f"indexer:{indexer_id}"]
    assert comp2.state == "ok"


@pytest.mark.req("FRG-NFR-011")
async def test_every_tracked_component_is_represented(db, tmp_path):
    await _add_indexer(db, name="NZBsu")
    await _add_client(db, name="SAB", implementation="sabnzbd")
    await _add_client(db, name="GetComics", implementation="ddl")
    root = tmp_path / "root"
    root.mkdir()
    async with db.write_session() as session:
        session.add(RootFolderRow(path=str(root)))

    components = await _service(db).component_view()
    kinds = {c.kind for c in components}
    assert {
        "comicvine",
        "indexer",
        "download_client",
        "ddl",
        "scheduler",
        "database",
        "root_folder",
        "disk",
    } <= kinds


@pytest.mark.req("FRG-NFR-011")
async def test_warnings_are_exactly_the_non_ok_subset(db):
    indexer_id = await _add_indexer(db)
    await ProviderBackoff(db).record_failure(
        PROVIDER_INDEXER, indexer_id, reason="boom"
    )
    service = _service(db)

    components = await service.component_view()
    warnings = await service.warnings()
    non_ok = [c for c in components if not c.ok]

    assert {w.source for w in warnings} == {c.component for c in non_ok}
    assert len(warnings) == len(non_ok)
    # Every warning derived from a non-ok component carries a remediation hint.
    assert all(w.remediation_hint for w in warnings)


@pytest.mark.req("FRG-NFR-011")
async def test_database_component_reflects_integrity_and_last_backup(db, tmp_path):
    cfg = db.db_path.parent
    service = _service(db)

    # (a) A failed integrity check → database error naming the failure.
    record_integrity(
        ok=False, check="integrity_check", source="pre-backup", detail="disk image malformed"
    )
    comp = _by_component(await service.component_view())["database"]
    assert comp.state == "error"
    assert "malformed" in (comp.message or "")

    # (b) Integrity ok but no scheduled backup yet → overdue/missing warning.
    reset_integrity()
    comp = _by_component(await service.component_view())["database"]
    assert comp.state == "degraded"
    assert "backup" in (comp.message or "").lower()

    # (c) Integrity ok and a fresh scheduled backup → ok.
    (cfg / "config.yaml").write_text("x: 1\n", encoding="utf-8")
    write_scheduled_backup(cfg / DB_FILENAME, cfg / "config.yaml", cfg, retention=7)
    comp = _by_component(await service.component_view())["database"]
    assert comp.state == "ok"
