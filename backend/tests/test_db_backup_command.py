"""The ``backup-database`` SCHED command + handler (FRG-DB-009, FRG-DB-012)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.commands import CommandService
from foragerr.commands.service import HandlerContext
from foragerr.config import Settings
from foragerr.db import DB_FILENAME, Database, JobHistoryRow, prepare_database
from foragerr.db.backup import SCHEDULED_PREFIX
from foragerr.db.backup_command import (
    BACKUP_DATABASE_TASK,
    _handle_backup_database,
    backup_task_registration,
)
from foragerr.health.state import current_integrity, reset_integrity

from conftest import eventually


@pytest.fixture(autouse=True)
def _reset_state():
    reset_integrity()
    yield
    reset_integrity()


def _prepared_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    (cfg / "config.yaml").write_text("port: 8789\n", encoding="utf-8")
    return cfg


def _context(cfg: Path) -> HandlerContext:
    return HandlerContext(
        db=Database(db_path=cfg / DB_FILENAME),
        bus=None,
        settings=Settings(config_dir=cfg),
        offload=asyncio.to_thread,
    )


@pytest.mark.req("FRG-DB-009")
async def test_handler_writes_a_scheduled_backup(tmp_path):
    cfg = _prepared_config(tmp_path)
    ctx = _context(cfg)

    summary = await _handle_backup_database(None, ctx)  # command unused by handler

    assert SCHEDULED_PREFIX in summary
    dirs = list((cfg / "backups").glob(f"{SCHEDULED_PREFIX}*"))
    assert len(dirs) == 1
    assert (dirs[0] / DB_FILENAME).exists()
    assert (dirs[0] / "config.yaml").exists()
    # The clean pre-backup check is recorded (clears any prior error).
    state = current_integrity()
    assert state is not None and state.ok and state.source == "pre-backup"
    await ctx.db.close()


@pytest.mark.req("FRG-DB-009")
@pytest.mark.req("FRG-DB-012")
async def test_corrupt_database_aborts_the_backup(tmp_path):
    cfg = _prepared_config(tmp_path)
    ctx = _context(cfg)
    # Corrupt the live DB file the pre-backup integrity check will read.
    (cfg / DB_FILENAME).write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)

    with pytest.raises(RuntimeError, match="integrity"):
        await _handle_backup_database(None, ctx)

    # No scheduled directory was written — the pool is never rotated for a copy
    # of corruption.
    assert not list((cfg / "backups").glob(f"{SCHEDULED_PREFIX}*"))
    state = current_integrity()
    assert state is not None and not state.ok and state.source == "pre-backup"
    assert state.detail
    await ctx.db.close()


@pytest.mark.req("FRG-DB-009")
async def test_backup_runs_through_the_command_backbone_with_job_history(
    tmp_path, command_registry
):
    """Force-running the task path enqueues the command, which completes with a
    job-history row — proving it rides SCHED (force-runnable, in history)."""
    cfg = _prepared_config(tmp_path)
    db = Database(db_path=cfg / DB_FILENAME)
    service = CommandService(db, Settings(config_dir=cfg), poll_interval=0.05)
    await service.start()
    try:
        record = await service.enqueue(BACKUP_DATABASE_TASK, triggered_by="manual")
        assert record.exclusivity_group == "backup"

        async def _completed() -> bool:
            got = await service.get(record.id)
            return got is not None and got.status == "completed"

        await eventually(_completed, timeout=5.0)

        async with db.read_session() as session:
            rows = (
                (
                    await session.execute(
                        select(JobHistoryRow).where(
                            JobHistoryRow.name == BACKUP_DATABASE_TASK
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert any(r.outcome == "completed" for r in rows)
        assert list((cfg / "backups").glob(f"{SCHEDULED_PREFIX}*"))
    finally:
        await service.drain(1.0)
        await db.close()


@pytest.mark.req("FRG-DB-009")
def test_task_registration_payload(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    payload = backup_task_registration(Settings(config_dir=cfg))
    assert payload["name"] == BACKUP_DATABASE_TASK
    assert payload["command_name"] == BACKUP_DATABASE_TASK
    assert payload["interval_seconds"] == 86_400  # daily default
    assert payload["min_interval_seconds"] == 3600  # documented minimum
