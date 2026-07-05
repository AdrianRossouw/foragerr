"""Command lifecycle, validation, and de-duplication (FRG-SCHED-001/003)."""

from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import func, select

from conftest import define_command, eventually
from foragerr.commands import CommandValidationError
from foragerr.commands.registry import register_handler
from foragerr.db import CommandRow, TERMINAL_STATUSES


async def _row_count(db) -> int:
    async with db.read_session() as session:
        return (await session.execute(select(func.count(CommandRow.id)))).scalar()


async def _status_terminal(service, command_id: int):
    record = await service.get(command_id)
    return record if record and record.status in TERMINAL_STATUSES else None


@pytest.mark.req("FRG-SCHED-001")
async def test_lifecycle_recorded_from_enqueue_to_terminal(db, service):
    record = await service.enqueue("noop", {"note": "lifecycle"}, priority=3)

    assert record.status == "queued"
    assert record.queued_at is not None

    final = await eventually(lambda: _status_terminal(service, record.id))
    assert final.status == "completed"
    assert final.name == "noop"
    assert final.priority == 3
    assert final.payload == {"note": "lifecycle"}  # persisted as JSON
    async with db.read_session() as session:
        row = await session.get(CommandRow, record.id)
        assert json.loads(row.payload) == {"note": "lifecycle"}
    # queued -> started -> completed with a derivable duration.
    assert final.queued_at <= final.started_at <= final.finished_at


@pytest.mark.req("FRG-SCHED-001")
async def test_handler_failure_preserves_error_and_worker_continues(db, service):
    define_command("t_fail")

    @register_handler("t_fail")
    async def _fail(command, ctx):
        raise RuntimeError("kaboom: could not reach indexer xyz")

    failed = await service.enqueue("t_fail", {"token": "one"})
    final = await eventually(lambda: _status_terminal(service, failed.id))
    assert final.status == "failed"
    assert final.error == "kaboom: could not reach indexer xyz"  # verbatim

    # The worker that ran it keeps processing subsequent commands normally.
    ok = await service.enqueue("noop", {"note": "still alive"})
    assert (await eventually(lambda: _status_terminal(service, ok.id))).status == (
        "completed"
    )


@pytest.mark.req("FRG-SCHED-001")
async def test_malformed_enqueue_rejected_without_a_row(db, service):
    with pytest.raises(CommandValidationError):
        await service.enqueue("no_such_command", {})

    with pytest.raises(CommandValidationError):
        await service.enqueue("noop", {"unexpected_field": 1})  # extra=forbid

    assert await _row_count(db) == 0  # no row was created either time


@pytest.mark.req("FRG-SCHED-003")
async def test_duplicate_enqueue_returns_existing_command(db, service, command_registry):
    define_command("t_gated")
    gate = asyncio.Event()

    @register_handler("t_gated")
    async def _gated(command, ctx):
        await gate.wait()

    first = await service.enqueue("t_gated", {"token": "same"})
    second = await service.enqueue("t_gated", {"token": "same"})

    assert second.id == first.id  # the existing command is returned
    assert await _row_count(db) == 1  # no second row

    gate.set()
    final_first = await eventually(lambda: _status_terminal(service, first.id))
    final_second = await eventually(lambda: _status_terminal(service, second.id))
    assert final_first.status == final_second.status == "completed"  # one execution


@pytest.mark.req("FRG-SCHED-003")
async def test_different_payloads_are_not_deduplicated(db, service):
    define_command("t_pay")
    gate = asyncio.Event()

    @register_handler("t_pay")
    async def _pay(command, ctx):
        await gate.wait()

    one = await service.enqueue("t_pay", {"token": "alpha"})
    two = await service.enqueue("t_pay", {"token": "beta"})

    assert one.id != two.id
    assert await _row_count(db) == 2  # two distinct rows

    gate.set()
    assert (await eventually(lambda: _status_terminal(service, one.id))).status == "completed"
    assert (await eventually(lambda: _status_terminal(service, two.id))).status == "completed"


@pytest.mark.req("FRG-SCHED-003")
async def test_terminal_commands_do_not_block_resubmission(db, service):
    first = await service.enqueue("noop", {"note": "run-me"})
    await eventually(lambda: _status_terminal(service, first.id))

    second = await service.enqueue("noop", {"note": "run-me"})  # equal-bodied

    assert second.id != first.id  # a NEW command row
    assert (await eventually(lambda: _status_terminal(service, second.id))).status == (
        "completed"
    )
    assert await _row_count(db) == 2
