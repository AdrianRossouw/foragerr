"""Interval scheduler: due/not-due, clamping, restart, force-run
(FRG-SCHED-006/007)."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

import pytest

from conftest import define_command, eventually
from foragerr.commands import IntervalScheduler
from foragerr.commands.registry import register_handler
from foragerr.db import ScheduledTaskRow, TERMINAL_STATUSES, utcnow


@pytest.fixture
async def scheduler(db, service):
    return IntervalScheduler(db, service, tick_seconds=60)


async def _set_last_run(db, name: str, when: dt.datetime | None) -> None:
    async with db.write_session() as session:
        row = await session.get(ScheduledTaskRow, name)
        row.last_run = when


async def _get_last_run(db, name: str) -> dt.datetime | None:
    async with db.read_session() as session:
        return (await session.get(ScheduledTaskRow, name)).last_run


async def _terminal(service, command_id: int):
    record = await service.get(command_id)
    return record if record and record.status in TERMINAL_STATUSES else None


@pytest.mark.req("FRG-SCHED-006")
async def test_due_task_enqueued_within_one_tick_and_last_run_updated(db, service, scheduler):
    await scheduler.register_task(
        "rss-sync", "noop", {"note": "rss"}, interval_seconds=300,
        min_interval_seconds=60,
    )
    await _set_last_run(db, "rss-sync", utcnow() - dt.timedelta(seconds=600))

    enqueued = await scheduler.tick()  # one tick is all it may take

    assert len(enqueued) == 1
    assert enqueued[0].triggered_by == "scheduled"
    last_run = await _get_last_run(db, "rss-sync")
    assert last_run is not None
    assert utcnow() - last_run < dt.timedelta(seconds=5)  # persisted update
    assert (await eventually(lambda: _terminal(service, enqueued[0].id))).status == (
        "completed"
    )


@pytest.mark.req("FRG-SCHED-006")
async def test_not_yet_due_task_is_not_enqueued(db, service, scheduler):
    await scheduler.register_task(
        "refresh", "noop", {"note": "refresh"}, interval_seconds=300,
        min_interval_seconds=60,
    )
    await _set_last_run(db, "refresh", utcnow())  # just ran

    assert await scheduler.tick() == []  # nothing enqueued on this tick


@pytest.mark.req("FRG-SCHED-006")
async def test_interval_below_minimum_is_clamped_with_warning(db, service, scheduler, caplog):
    with caplog.at_level(logging.WARNING, logger="foragerr.scheduler"):
        definition = await scheduler.register_task(
            "eager", "noop", {"note": "eager"}, interval_seconds=5,
            min_interval_seconds=120,
        )

    assert definition.interval_seconds == 120  # the documented minimum wins
    clamp_logs = [r for r in caplog.records if "clamped" in r.getMessage()]
    assert clamp_logs and "eager" in clamp_logs[0].getMessage()

    # The effective interval is what the scheduler actually uses.
    await _set_last_run(db, "eager", utcnow() - dt.timedelta(seconds=30))
    assert await scheduler.tick() == []  # 30s elapsed < 120s effective


@pytest.mark.req("FRG-SCHED-006")
async def test_loop_tick_is_clamped_to_sixty_seconds(db, service):
    scheduler = IntervalScheduler(db, service, tick_seconds=3600)
    assert scheduler.tick_seconds <= 60


@pytest.mark.req("FRG-SCHED-006")
async def test_restart_honors_persisted_last_run(db, service):
    first = IntervalScheduler(db, service, tick_seconds=60)
    await first.register_task(
        "pull-list", "noop", {"note": "pull"}, interval_seconds=300,
        min_interval_seconds=60,
    )
    just_ran = utcnow() - dt.timedelta(seconds=10)
    await _set_last_run(db, "pull-list", just_ran)

    # "Restart": a brand-new scheduler instance over the same database.
    second = IntervalScheduler(db, service, tick_seconds=60)
    await second.register_task(
        "pull-list", "noop", {"note": "pull"}, interval_seconds=300,
        min_interval_seconds=60,
    )

    assert await _get_last_run(db, "pull-list") == just_ran  # timer NOT reset
    assert await second.tick() == []  # does not fire immediately on startup

    await _set_last_run(db, "pull-list", utcnow() - dt.timedelta(seconds=301))
    assert len(await second.tick()) == 1  # fires at last_run + interval


@pytest.mark.req("FRG-SCHED-007")
async def test_force_run_enqueues_immediately_and_is_trackable(db, service, scheduler):
    await scheduler.register_task(
        "folder-scan", "noop", {"note": "scan"}, interval_seconds=3600,
        min_interval_seconds=60,
    )
    await _set_last_run(db, "folder-scan", utcnow())  # NOT currently due

    record = await scheduler.force_run("folder-scan")

    assert record.id is not None  # trackable command id
    final = await eventually(lambda: _terminal(service, record.id))
    assert final.status == "completed"  # ran without waiting for the schedule


@pytest.mark.req("FRG-SCHED-007")
async def test_force_run_resets_the_recurring_timer(db, service, scheduler):
    await scheduler.register_task(
        "backup", "noop", {"note": "backup"}, interval_seconds=300,
        min_interval_seconds=60,
    )
    nearly_due = utcnow() - dt.timedelta(seconds=295)
    await _set_last_run(db, "backup", nearly_due)

    record = await scheduler.force_run("backup")
    await eventually(lambda: _terminal(service, record.id))

    last_run = await _get_last_run(db, "backup")
    assert last_run > nearly_due  # updated to the force-run execution
    assert await scheduler.tick() == []  # next fire is one FULL interval away


@pytest.mark.req("FRG-SCHED-007")
async def test_force_run_of_running_task_deduplicates(db, service, scheduler, command_registry):
    define_command("t_sched_gated")
    gate = asyncio.Event()

    @register_handler("t_sched_gated")
    async def _gated(command, ctx):
        await gate.wait()

    await scheduler.register_task(
        "slow-task", "t_sched_gated", {"token": "x"}, interval_seconds=3600,
        min_interval_seconds=60,
    )
    first = await scheduler.force_run("slow-task")
    second = await scheduler.force_run("slow-task")  # equal-bodied, in flight

    assert second.id == first.id  # existing command returned, no duplicate
    gate.set()
    final = await eventually(lambda: _terminal(service, first.id))
    assert final.status == "completed"
