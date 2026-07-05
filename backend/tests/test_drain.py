"""Graceful queue drain on shutdown (FRG-SCHED-011)."""

from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import select

from conftest import define_command, eventually
from foragerr.commands import CommandService
from foragerr.commands.registry import register_handler
from foragerr.db import CommandRow


async def _status(db, command_id: int) -> str:
    async with db.read_session() as session:
        return (await session.get(CommandRow, command_id)).status


async def _started(service, command_id: int):
    record = await service.get(command_id)
    return record if record and record.status == "started" else None


@pytest.mark.req("FRG-SCHED-011")
async def test_shutdown_stops_new_claims_and_lets_inflight_finish(db, command_registry):
    define_command("t_drain", workload_class="search")  # pool size 1
    gate = asyncio.Event()

    @register_handler("t_drain")
    async def _drain_cmd(command, ctx):
        await gate.wait()
        return "finished cleanly"

    service = CommandService(db, poll_interval=0.05)
    await service.start()

    inflight = await service.enqueue("t_drain", {"token": "inflight"})
    await eventually(lambda: _started(service, inflight.id))
    queued = [
        await service.enqueue("t_drain", {"token": f"waiting-{i}"}) for i in range(2)
    ]

    async def release_soon() -> None:
        await asyncio.sleep(0.15)
        gate.set()

    releaser = asyncio.create_task(release_soon())
    await service.drain(grace_seconds=5.0)  # the shutdown signal
    await releaser

    # In-flight finished inside the grace and reached a terminal status.
    assert await _status(db, inflight.id) == "completed"
    record = await service.get(inflight.id)
    assert record.result == "finished cleanly"
    # No queued command was claimed after the signal.
    for r in queued:
        assert await _status(db, r.id) == "queued"


@pytest.mark.req("FRG-SCHED-011")
async def test_queued_commands_persist_untouched_across_graceful_shutdown(
    db, command_registry
):
    service = CommandService(db, poll_interval=0.05)  # workers never started:
    a = await service.enqueue("noop", {"note": "later-1"})  # everything stays queued
    b = await service.enqueue("noop", {"note": "later-2"})
    await service.drain(grace_seconds=1.0)  # graceful shutdown

    # "Restart": a fresh service over the same database.
    restarted = CommandService(db, poll_interval=0.05)
    assert await restarted.recover_orphans() == 0  # no orphaned started rows
    assert await _status(db, a.id) == "queued"
    assert await _status(db, b.id) == "queued"

    await restarted.start()
    try:
        await eventually(lambda: _terminal_status(db, a.id))
        await eventually(lambda: _terminal_status(db, b.id))
    finally:
        await restarted.drain(1.0)


async def _terminal_status(db, command_id: int):
    status = await _status(db, command_id)
    return status if status in ("completed", "failed", "cancelled") else None


@pytest.mark.req("FRG-SCHED-011")
async def test_grace_period_is_bounded_and_stragglers_go_to_recovery(
    db, command_registry
):
    define_command("t_hang")

    @register_handler("t_hang")
    async def _hang(command, ctx):
        await asyncio.Event().wait()  # never finishes

    service = CommandService(db, poll_interval=0.05)
    await service.start()
    record = await service.enqueue("t_hang", {"token": "stuck"})
    await eventually(lambda: _started(service, record.id))

    start = time.monotonic()
    await service.drain(grace_seconds=0.3)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0  # the process exits within the bound
    # The row is NOT silently terminal — it is left for orphan recovery...
    assert await _status(db, record.id) == "started"
    fresh = CommandService(db)
    assert await fresh.recover_orphans() == 1  # ...which re-queues it
    assert await _status(db, record.id) == "queued"


@pytest.mark.req("FRG-SCHED-011")
@pytest.mark.req("FRG-DB-001")
def test_full_app_lifecycle_starts_runs_and_drains_cleanly(config_dir):
    """The wired app: db + workers + scheduler up, command round-trip, then a
    clean shutdown through the reversed lifespan hooks (drain before db close)."""
    from fastapi.testclient import TestClient

    from foragerr.app import create_app

    app = create_app()
    with TestClient(app) as client:
        assert app.state.db is not None
        assert app.state.commands.health()["status"] == "up"
        # housekeeping (sched area), the search area's scheduled backlog +
        # release-cache prune tasks (m1-search-indexers), and the DDL queue
        # drainer (m1-downloads, ddl area).
        assert app.state.scheduler.task_names() == [
            "backlog-search",
            "housekeeping",
            "process-ddl-queue",
            "prune-release-cache",
        ]

        async def round_trip():
            record = await app.state.commands.enqueue("noop", {"note": "demo"})
            return await eventually(
                lambda: _app_terminal(app.state.commands, record.id)
            )

        # TestClient's portal runs the coroutine on the app's event loop.
        final = client.portal.call(round_trip)
        assert final.status == "completed"

    # Exiting the context ran the shutdown hooks: drain + WAL checkpoint.
    assert (config_dir / "foragerr.db").exists()


async def _app_terminal(service, command_id: int):
    record = await service.get(command_id)
    return record if record and record.status in ("completed", "failed") else None
