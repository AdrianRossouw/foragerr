"""Engine PRAGMAs, WAL reader behavior, FK enforcement, single-file state
(FRG-DB-001, FRG-DB-005)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from foragerr.db import CommandRow, Database, JobHistoryRow, utcnow


def _command_row(**overrides) -> CommandRow:
    defaults = dict(
        name="noop",
        status="queued",
        payload="{}",
        payload_hash="h",
        queued_at=utcnow(),
    )
    defaults.update(overrides)
    return CommandRow(**defaults)


@pytest.mark.req("FRG-DB-005")
async def test_every_pooled_connection_reports_required_pragmas(migrated_dir):
    db = Database(db_path=migrated_dir / "foragerr.db", busy_timeout_ms=4321)
    try:
        # Hold several connections open at once so the pool has to CREATE
        # fresh ones — each must carry the PRAGMAs.
        conns = [await db.engine.connect() for _ in range(3)]
        try:
            for conn in conns:
                journal = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
                fks = (await conn.execute(text("PRAGMA foreign_keys"))).scalar()
                sync = (await conn.execute(text("PRAGMA synchronous"))).scalar()
                busy = (await conn.execute(text("PRAGMA busy_timeout"))).scalar()
                assert journal == "wal"
                assert fks == 1
                assert sync >= 1  # NORMAL(1) or stricter
                assert busy == 4321  # the configured, non-zero value
        finally:
            for conn in conns:
                await conn.close()
    finally:
        await db.close()


@pytest.mark.req("FRG-DB-005")
async def test_reader_not_blocked_by_open_write_transaction(db):
    async with db.write_session() as session:
        session.add(_command_row())
        await session.flush()  # write transaction open, uncommitted

        async def read_count() -> int:
            async with db.read_session() as reader:
                return (
                    await reader.execute(select(func.count(CommandRow.id)))
                ).scalar()

        # Completes without waiting for the writer and sees last-committed data.
        count = await asyncio.wait_for(read_count(), timeout=2.0)
        assert count == 0

    async with db.read_session() as reader:
        assert (await reader.execute(select(func.count(CommandRow.id)))).scalar() == 1


@pytest.mark.req("FRG-DB-005")
async def test_foreign_key_constraints_enforced(db):
    with pytest.raises(IntegrityError):
        async with db.write_session() as session:
            session.add(
                JobHistoryRow(
                    command_id=999_999,  # no such command
                    name="ghost",
                    triggered_by="manual",
                    outcome="completed",
                )
            )

    async with db.read_session() as reader:
        count = (await reader.execute(select(func.count(JobHistoryRow.id)))).scalar()
    assert count == 0  # nothing dangling persisted


@pytest.mark.req("FRG-DB-001")
async def test_fresh_start_creates_single_database_under_config(config_dir: Path):
    from fastapi.testclient import TestClient

    from foragerr.app import create_app

    app = create_app()
    with TestClient(app):
        assert (config_dir / "foragerr.db").exists()

    db_files = {p.name for p in config_dir.rglob("*.db")}
    assert db_files == {"foragerr.db"}  # exactly one database file


@pytest.mark.req("FRG-DB-001")
async def test_state_survives_instance_recreate_on_same_config_dir(migrated_dir):
    db_path = migrated_dir / "foragerr.db"
    first = Database(db_path=db_path)
    async with first.write_session() as session:
        session.add(_command_row(name="noop", payload_hash="persisted"))
    await first.close()

    second = Database(db_path=db_path)  # "new container, same volume"
    try:
        async with second.read_session() as reader:
            rows = (await reader.execute(select(CommandRow))).scalars().all()
        assert [r.payload_hash for r in rows] == ["persisted"]
    finally:
        await second.close()
