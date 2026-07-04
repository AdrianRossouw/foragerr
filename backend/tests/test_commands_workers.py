"""Priority, exclusivity, worker pools, and blocking-work offload
(FRG-SCHED-004/005)."""

from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import select

from conftest import define_command, eventually
from foragerr.db import CommandRow, TERMINAL_STATUSES


async def _statuses(db, name_prefix: str = "") -> dict[int, str]:
    async with db.read_session() as session:
        rows = (await session.execute(select(CommandRow))).scalars().all()
    return {r.id: r.status for r in rows if r.name.startswith(name_prefix)}


async def _all_terminal(db, ids) -> bool:
    statuses = await _statuses(db)
    return all(statuses.get(i) in TERMINAL_STATUSES for i in ids)


@pytest.mark.req("FRG-SCHED-004")
async def test_higher_priority_command_jumps_the_queue(db, service):
    from foragerr.commands.registry import register_handler

    define_command("t_prio", workload_class="search")  # pool size 1
    order: list[str] = []
    gate = asyncio.Event()

    @register_handler("t_prio")
    async def _prio(command, ctx):
        if command.token == "blocker":
            await gate.wait()
        else:
            order.append(command.token)

    blocker = await service.enqueue("t_prio", {"token": "blocker"})
    await eventually(
        lambda: _statuses(db), timeout=5.0
    )  # let it get claimed
    await eventually(
        lambda: _is_started(service, blocker.id)
    )

    lows = [
        await service.enqueue("t_prio", {"token": f"low-{i}"}, priority=0)
        for i in range(3)
    ]
    high = await service.enqueue("t_prio", {"token": "high"}, priority=10)
    gate.set()

    await eventually(lambda: _all_terminal(db, [c.id for c in lows + [high, blocker]]))
    assert order[0] == "high"  # claimed before the earlier low-priority ones
    assert set(order[1:]) == {"low-0", "low-1", "low-2"}


async def _is_started(service, command_id: int):
    record = await service.get(command_id)
    return record if record and record.status == "started" else None


@pytest.mark.req("FRG-SCHED-004")
async def test_exclusivity_group_serializes_execution(db, service):
    from foragerr.commands.registry import register_handler

    define_command("t_excl", workload_class="default", exclusivity_group="grp")
    active = 0
    max_active = 0

    @register_handler("t_excl")
    async def _excl(command, ctx):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1

    # Two default workers COULD run both concurrently; the group must not.
    records = [
        await service.enqueue("t_excl", {"token": f"n{i}"}) for i in range(3)
    ]
    await eventually(lambda: _all_terminal(db, [r.id for r in records]))
    assert max_active == 1  # never both in started/executing simultaneously


@pytest.mark.req("FRG-SCHED-004")
async def test_exclusivity_does_not_block_unrelated_work(db, service):
    from foragerr.commands.registry import register_handler

    define_command("t_long", workload_class="default", exclusivity_group="busy-grp")
    define_command("t_free", workload_class="default")
    gate = asyncio.Event()

    @register_handler("t_long")
    async def _long(command, ctx):
        await gate.wait()

    @register_handler("t_free")
    async def _free(command, ctx):
        return "done"

    holder = await service.enqueue("t_long", {"token": "hold"})
    await eventually(lambda: _is_started(service, holder.id))

    free = await service.enqueue("t_free", {"token": "go"})
    final = await eventually(lambda: _terminal(service, free.id))
    assert final.status == "completed"  # ran while the group lock was held

    gate.set()
    await eventually(lambda: _terminal(service, holder.id))


async def _terminal(service, command_id: int):
    record = await service.get(command_id)
    return record if record and record.status in TERMINAL_STATUSES else None


@pytest.mark.req("FRG-SCHED-005")
async def test_default_pool_sizes_cap_per_class_concurrency(db, service):
    from foragerr.commands.registry import register_handler

    gate = asyncio.Event()
    for cls in ("search", "download", "pp", "default"):
        define_command(f"t_{cls}", workload_class=cls)

        @register_handler(f"t_{cls}")
        async def _blocked(command, ctx):
            await gate.wait()

    per_class = 4
    ids: list[int] = []
    for cls in ("search", "download", "pp", "default"):
        for i in range(per_class):
            record = await service.enqueue(f"t_{cls}", {"token": f"{cls}-{i}"})
            ids.append(record.id)

    async def started_counts() -> dict[str, int] | None:
        async with db.read_session() as session:
            rows = (
                (
                    await session.execute(
                        select(CommandRow).where(CommandRow.status == "started")
                    )
                )
                .scalars()
                .all()
            )
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.workload_class] = counts.get(row.workload_class, 0) + 1
        expected = {"search": 1, "download": 1, "pp": 1, "default": 2}
        return counts if counts == expected else None

    await eventually(started_counts)  # caps reached...
    await asyncio.sleep(0.3)  # ...and NEVER exceeded while saturated
    assert await started_counts() is not None

    gate.set()
    await eventually(lambda: _all_terminal(db, ids))


@pytest.mark.req("FRG-SCHED-005")
async def test_saturated_class_does_not_starve_another(db, service):
    from foragerr.commands.registry import register_handler

    define_command("t_pp_busy", workload_class="pp")
    gate = asyncio.Event()

    @register_handler("t_pp_busy")
    async def _busy(command, ctx):
        await gate.wait()

    for i in range(3):  # saturate pp (pool size 1) with a long job + backlog
        await service.enqueue("t_pp_busy", {"token": f"pp-{i}"})

    start = time.monotonic()
    search = await service.enqueue("noop", {"note": "search-now"})
    final = await eventually(lambda: _terminal(service, search.id), timeout=2.0)
    latency = time.monotonic() - start

    assert final.status == "completed"
    assert latency < 1.5  # normal latency, unaffected by the busy pp pool
    gate.set()


@pytest.mark.req("FRG-SCHED-005")
async def test_blocking_work_offload_keeps_event_loop_responsive(db, service):
    from foragerr.commands.registry import register_handler

    define_command("t_block_io")

    @register_handler("t_block_io")
    async def _block_io(command, ctx):
        # Blocking work goes through the offload helper (asyncio.to_thread).
        await ctx.offload(time.sleep, 0.4)
        return "extracted"

    record = await service.enqueue("t_block_io", {"token": "cbz"})
    await eventually(lambda: _is_started(service, record.id))

    # While the blocking work runs, the event loop must stay responsive.
    start = time.monotonic()
    for _ in range(10):
        await asyncio.sleep(0.01)
    elapsed = time.monotonic() - start
    assert elapsed < 0.35  # not serialized behind the 0.4s blocking sleep

    final = await eventually(lambda: _terminal(service, record.id))
    assert final.status == "completed"
    assert final.result == "extracted"
