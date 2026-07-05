"""Persisted job history: per-execution rows, restart survival, retention
pruning (FRG-SCHED-008)."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from conftest import define_command, eventually
from foragerr.commands import CommandService, IntervalScheduler, prune_job_history
from foragerr.commands.registry import register_handler
from foragerr.db import (
    Database,
    JobHistoryRow,
    TERMINAL_STATUSES,
    utcnow,
)


async def _terminal(service, command_id: int):
    record = await service.get(command_id)
    return record if record and record.status in TERMINAL_STATUSES else None


async def _history(db) -> list[JobHistoryRow]:
    async with db.read_session() as session:
        return (
            (await session.execute(select(JobHistoryRow).order_by(JobHistoryRow.id)))
            .scalars()
            .all()
        )


@pytest.mark.req("FRG-SCHED-008")
async def test_every_execution_writes_a_history_row_with_trigger_and_outcome(
    db, service
):
    define_command("t_hist_fail")

    @register_handler("t_hist_fail")
    async def _fail(command, ctx):
        raise ValueError("metadata provider returned HTTP 503 (server melted)")

    scheduler = IntervalScheduler(db, service, tick_seconds=60)
    await scheduler.register_task(
        "hist-task", "noop", {"note": "sched"}, interval_seconds=60,
        min_interval_seconds=60,
    )

    scheduled = (await scheduler.tick())[0]  # scheduled trigger
    manual = await service.enqueue("noop", {"note": "by-hand"})  # manual trigger
    failed = await service.enqueue("t_hist_fail", {"token": "f"})

    for record in (scheduled, manual, failed):
        await eventually(lambda r=record: _terminal(service, r.id))

    history = {h.command_id: h for h in await _history(db)}
    assert history[scheduled.id].triggered_by == "scheduled"
    assert history[manual.id].triggered_by == "manual"
    for h in history.values():
        assert h.started_at is not None and h.finished_at is not None
        assert h.started_at <= h.finished_at  # duration derivable
    assert history[manual.id].outcome == "completed"
    assert history[failed.id].outcome == "failed"
    assert history[failed.id].error == (
        "metadata provider returned HTTP 503 (server melted)"  # verbatim
    )


@pytest.mark.req("FRG-SCHED-008")
async def test_history_survives_restart(migrated_dir, command_registry):
    db_path = migrated_dir / "foragerr.db"
    first_db = Database(db_path=db_path)
    first = CommandService(first_db, poll_interval=0.05)
    await first.start()
    record = await first.enqueue("noop", {"note": "before-restart"})
    await eventually(lambda: _terminal(first, record.id))
    before = [(h.command_id, h.outcome) for h in await _history(first_db)]
    await first.drain(1.0)
    await first_db.close()

    second_db = Database(db_path=db_path)  # restart
    try:
        after = [(h.command_id, h.outcome) for h in await _history(second_db)]
        assert after == before  # previous runs unchanged by the restart
        assert (record.id, "completed") in after
    finally:
        await second_db.close()


@pytest.mark.req("FRG-SCHED-008")
async def test_housekeeping_prunes_history_by_retention_window(db, service):
    now = utcnow()
    async with db.write_session() as session:
        for age_days, name in ((45, "ancient"), (31, "old"), (2, "recent")):
            session.add(
                JobHistoryRow(
                    name=name,
                    triggered_by="scheduled",
                    started_at=now - dt.timedelta(days=age_days, minutes=5),
                    finished_at=now - dt.timedelta(days=age_days),
                    outcome="completed",
                )
            )

    pruned = await prune_job_history(db, retention_days=30)

    assert pruned == 2
    names = [h.name for h in await _history(db)]
    assert "ancient" not in names and "old" not in names
    assert "recent" in names  # rows inside the window are untouched


@pytest.mark.req("FRG-SCHED-008")
async def test_housekeeping_command_runs_the_pruning(db, service):
    now = utcnow()
    async with db.write_session() as session:
        session.add(
            JobHistoryRow(
                name="stale",
                triggered_by="scheduled",
                started_at=now - dt.timedelta(days=99),
                finished_at=now - dt.timedelta(days=99),
                outcome="completed",
            )
        )

    record = await service.enqueue("housekeeping")
    final = await eventually(lambda: _terminal(service, record.id))

    assert final.status == "completed"
    assert "pruned 1" in final.result
    names = [h.name for h in await _history(db)]
    assert "stale" not in names
    assert "housekeeping" in [h.name for h in await _history(db)]  # own row kept
