"""Persisted queue survival and orphan recovery across restarts
(FRG-SCHED-002)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from conftest import eventually
from foragerr.commands import CommandService
from foragerr.db import CommandRow, Database, JobHistoryRow, TERMINAL_STATUSES


async def _terminal(service, command_id: int):
    record = await service.get(command_id)
    return record if record and record.status in TERMINAL_STATUSES else None


@pytest.mark.req("FRG-SCHED-002")
async def test_queued_commands_survive_unclean_restart(migrated_dir, command_registry):
    db_path = migrated_dir / "foragerr.db"

    # First process lifetime: enqueue but never start workers, then die
    # without any graceful shutdown (no drain, no checkpoint).
    first_db = Database(db_path=db_path)
    first = CommandService(first_db)
    a = await first.enqueue("noop", {"note": "one"})
    b = await first.enqueue("noop", {"note": "two"})
    await first_db.engine.dispose()  # simulated kill: no drain, no close()

    # Second lifetime: rows are still queued and run to a terminal status
    # without re-submission.
    second_db = Database(db_path=db_path)
    second = CommandService(second_db, poll_interval=0.05)
    async with second_db.read_session() as session:
        rows = (await session.execute(select(CommandRow))).scalars().all()
    assert {r.id: r.status for r in rows} == {a.id: "queued", b.id: "queued"}

    await second.start()
    try:
        assert (await eventually(lambda: _terminal(second, a.id))).status == "completed"
        assert (await eventually(lambda: _terminal(second, b.id))).status == "completed"
    finally:
        await second.drain(1.0)
        await second_db.close()


@pytest.mark.req("FRG-SCHED-002")
async def test_orphaned_started_command_requeued_and_visible_in_record(
    migrated_dir, command_registry
):
    db_path = migrated_dir / "foragerr.db"
    dead_db = Database(db_path=db_path)
    dead = CommandService(dead_db)
    record = await dead.enqueue("noop", {"note": "orphan"})
    # Simulate a kill mid-execution: the row is stuck in 'started'.
    async with dead_db.write_session() as session:
        row = await session.get(CommandRow, record.id)
        row.status = "started"
        row.started_at = row.queued_at
    await dead_db.engine.dispose()

    new_db = Database(db_path=db_path)
    service = CommandService(new_db, poll_interval=0.05)
    await service.start()  # startup recovery re-queues the orphan
    try:
        final = await eventually(lambda: _terminal(service, record.id))
        assert final.status == "completed"  # ran again to completion

        async with new_db.read_session() as session:
            history = (
                (
                    await session.execute(
                        select(JobHistoryRow).where(
                            JobHistoryRow.command_id == record.id
                        ).order_by(JobHistoryRow.id)
                    )
                )
                .scalars()
                .all()
            )
        outcomes = [h.outcome for h in history]
        assert "interrupted" in outcomes  # the interruption is visible
        assert outcomes[-1] == "completed"  # and so is the successful re-run
    finally:
        await service.drain(1.0)
        await new_db.close()


@pytest.mark.req("FRG-SCHED-002")
async def test_orphan_recovery_is_idempotent(db, command_registry):
    service = CommandService(db)  # workers never started
    record = await service.enqueue("noop", {"note": "idem"})
    async with db.write_session() as session:
        row = await session.get(CommandRow, record.id)
        row.status = "started"

    assert await service.recover_orphans() == 1
    assert await service.recover_orphans() == 0  # second run finds nothing

    async with db.read_session() as session:
        rows = (await session.execute(select(CommandRow))).scalars().all()
        history = (await session.execute(select(JobHistoryRow))).scalars().all()
    assert [r.status for r in rows] == ["queued"]  # exactly one queued row
    assert [h.outcome for h in history] == ["interrupted"]  # exactly one record
