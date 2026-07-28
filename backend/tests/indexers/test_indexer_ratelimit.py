"""Per-indexer request-spacing gate (FRG-IDX-008, FRG-NFR-005) and the
interactive precedence taken at it (FRG-SRCH-015).

Precedence is a reordering of WAITERS, never a spacing exemption: every test
here that mixes the two classes also asserts the spacing invariant on the
combined timeline, so a "faster interactive search" can never be bought with a
politeness violation.
"""

from __future__ import annotations

import asyncio

import pytest

from foragerr.indexers import ratelimit
from indexers_support import _reset_indexer_gates  # noqa: F401  (autouse fixture)

INTERVAL = 0.2


@pytest.mark.req("FRG-IDX-008")
@pytest.mark.req("FRG-NFR-005")
async def test_consecutive_requests_to_one_indexer_are_spaced():
    loop = asyncio.get_running_loop()
    stamps: list[float] = []
    for _ in range(3):
        await ratelimit.acquire(1, INTERVAL)
        stamps.append(loop.time())
    gaps = [stamps[i + 1] - stamps[i] for i in range(len(stamps) - 1)]
    assert all(gap >= INTERVAL * 0.9 for gap in gaps), gaps


@pytest.mark.req("FRG-IDX-008")
async def test_different_indexers_are_not_serialized_against_each_other():
    loop = asyncio.get_running_loop()
    await ratelimit.acquire(1, INTERVAL)  # indexer 1 sets its last-request time
    start = loop.time()
    await ratelimit.acquire(2, INTERVAL)  # a DIFFERENT indexer, own gate
    assert loop.time() - start < INTERVAL / 2  # not delayed by indexer 1


@pytest.mark.req("FRG-IDX-008")
async def test_spacing_holds_across_paging_of_one_indexer():
    # Simulate paged requests to one indexer: every acquire is spaced, so a
    # multi-page fetch cannot burst.
    loop = asyncio.get_running_loop()
    await ratelimit.acquire(5, INTERVAL)
    start = loop.time()
    await ratelimit.acquire(5, INTERVAL)  # "next page" — must wait a full slot
    assert loop.time() - start >= INTERVAL * 0.9


# --- interactive precedence at the gate (FRG-SRCH-015) ----------------------

#: Small enough to keep these tests sub-second, above the loop's noise floor.
FAST = 0.1
#: How many background requests are kept queued on the one indexer — the "hog".
HOGS = 8


async def _hog_pack(indexer_id: int, stamps: list[tuple[str, float]], stop):
    """``HOGS`` background acquires looping continuously on one indexer.

    This is what an add sweep or the backlog walk looks like at the gate: a
    standing queue of politely spaced requests that never empties on its own."""
    loop = asyncio.get_running_loop()

    async def hog():
        while not stop.is_set():
            await ratelimit.acquire(indexer_id, FAST)
            stamps.append(("background", loop.time()))

    return [asyncio.create_task(hog()) for _ in range(HOGS)]


async def _stop_pack(tasks, stop) -> None:
    stop.set()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def _gaps(stamps: list[tuple[str, float]]) -> list[float]:
    times = sorted(t for _, t in stamps)
    return [times[i + 1] - times[i] for i in range(len(times) - 1)]


@pytest.mark.req("FRG-SRCH-015")
async def test_an_interactive_request_jumps_a_background_queue():
    """The rig finding: a background sweep occupying an indexer's gate made an
    interactive search wait out the WHOLE queue and return starved-empty. A
    priority acquire is admitted at the next politeness slot instead."""
    loop = asyncio.get_running_loop()
    stamps: list[tuple[str, float]] = []
    stop = asyncio.Event()
    hogs = await _hog_pack(1, stamps, stop)
    try:
        await asyncio.sleep(FAST * 3)  # let a real queue form on the gate
        assert len(stamps) >= 2, "the hog pack never got going"
        admitted_before = len(stamps)

        start = loop.time()
        await ratelimit.acquire(1, FAST, priority=True)
        waited = loop.time() - start
        stamps.append(("interactive", loop.time()))

        # The timing-independent statement of precedence: once the interactive
        # demand is announced, AT MOST the one background request already
        # sleeping out its slot can be admitted before it — never the queue.
        assert len(stamps) - admitted_before - 1 <= 1
        # ...and in wall time that is a politeness slot or two, not HOGS of them
        # (a FIFO gate would have made this wait >= HOGS * FAST).
        assert waited < FAST * 3, f"interactive waited {waited:.3f}s"
    finally:
        await _stop_pack(hogs, stop)


@pytest.mark.req("FRG-SRCH-015")
async def test_the_very_next_slot_goes_to_the_interactive_request():
    """"Next politeness slot" means the next one, full stop — including the
    slot a background waiter is already sitting out.

    Letting that sleeper keep its slot would cost every interactive request TWO
    intervals instead of one, and an interactive search is a ladder of requests:
    doubled, it stops fitting in its budget and the operator is back to
    starved-empty partials."""
    loop = asyncio.get_running_loop()
    await ratelimit.acquire(5, FAST)  # the last request that really went out
    stamped = loop.time()

    background = asyncio.create_task(ratelimit.acquire(5, FAST))
    await asyncio.sleep(FAST / 4)  # it is now sleeping out the next slot
    assert not background.done()

    await ratelimit.acquire(5, FAST, priority=True)
    admitted = loop.time() - stamped
    # Spacing honoured (never early)...
    assert admitted >= FAST * 0.9, admitted
    # ...and it is THE next slot, not the one after the background waiter's.
    assert admitted < FAST * 1.6, admitted
    assert not background.done(), "the background waiter kept the slot"

    # The background waiter is not dropped — it takes the following slot.
    await background
    assert loop.time() - stamped >= FAST * 1.9


@pytest.mark.req("FRG-SRCH-015")
@pytest.mark.req("FRG-IDX-008")
async def test_spacing_is_never_violated_when_the_classes_are_mixed():
    """Precedence reorders waiters; it must not let two requests out inside one
    politeness slot. The whole mixed timeline is checked, not each class."""
    stamps: list[tuple[str, float]] = []
    stop = asyncio.Event()
    hogs = await _hog_pack(2, stamps, stop)
    loop = asyncio.get_running_loop()
    try:
        await asyncio.sleep(FAST * 2)
        for _ in range(4):  # an interactive search's own paged requests
            await ratelimit.acquire(2, FAST, priority=True)
            stamps.append(("interactive", loop.time()))
    finally:
        await _stop_pack(hogs, stop)

    gaps = _gaps(stamps)
    assert len(stamps) >= 6, stamps
    assert min(gaps) >= FAST * 0.9, gaps
    assert any(kind == "interactive" for kind, _ in stamps)
    assert any(kind == "background" for kind, _ in stamps)


@pytest.mark.req("FRG-SRCH-015")
async def test_an_interactive_ladder_costs_one_slot_per_request_under_load():
    """What the time budget actually depends on: an interactive search is a
    LADDER of gate-spaced requests, so the per-request cost under contention is
    what decides whether it fits its budget. One slot each is the floor the
    politeness interval sets; anything more is the sweep leaking into the
    operator's wait."""
    loop = asyncio.get_running_loop()
    stamps: list[tuple[str, float]] = []
    stop = asyncio.Event()
    hogs = await _hog_pack(6, stamps, stop)
    rungs = 5
    try:
        await asyncio.sleep(FAST * 2)
        start = loop.time()
        for _ in range(rungs):
            await ratelimit.acquire(6, FAST, priority=True)
            stamps.append(("interactive", loop.time()))
            await asyncio.sleep(0.005)  # the request itself + parsing
        ladder = loop.time() - start
    finally:
        await _stop_pack(hogs, stop)

    # One slot per rung, plus room for the slot in flight on arrival — against
    # the len(hogs) * rungs slots a FIFO gate would have charged.
    assert ladder <= FAST * (rungs + 2), f"{ladder:.3f}s for {rungs} requests"
    assert min(_gaps(stamps)) >= FAST * 0.9  # ...and never at politeness' cost


@pytest.mark.req("FRG-SRCH-015")
async def test_background_work_resumes_once_the_interactive_demand_drains():
    """Precedence must not become starvation: the moment no priority waiter is
    present the background queue proceeds again, at its normal spacing."""
    stamps: list[tuple[str, float]] = []
    stop = asyncio.Event()
    hogs = await _hog_pack(3, stamps, stop)
    try:
        await asyncio.sleep(FAST * 2)
        await ratelimit.acquire(3, FAST, priority=True)
        drained = len(stamps)
        await asyncio.sleep(FAST * 3)
        assert len(stamps) > drained, "background never resumed after the drain"
    finally:
        await _stop_pack(hogs, stop)

    gate = ratelimit._gate_for(3)
    assert gate._priority_waiters == 0
    assert gate._drained.is_set()


@pytest.mark.req("FRG-SRCH-015")
async def test_a_cancelled_priority_waiter_never_wedges_background_work():
    """A cancelled interactive search (its budget lapsing, the client hanging
    up) must not leave the gate believing priority demand is still pending —
    that would wedge every background request on this indexer for good."""
    stamps: list[tuple[str, float]] = []
    stop = asyncio.Event()
    hogs = await _hog_pack(4, stamps, stop)
    try:
        await asyncio.sleep(FAST * 2)
        gate = ratelimit._gate_for(4)

        # A DELIBERATELY long spacing for this one acquire, so it is certain to
        # still be waiting when it is cancelled (a prioritised acquire is
        # normally admitted almost at once — which is the point of the feature
        # and would otherwise race this test).
        waiter = asyncio.create_task(ratelimit.acquire(4, FAST * 20, priority=True))
        await asyncio.sleep(FAST / 4)  # let it register its demand
        assert gate._priority_waiters == 1
        assert not gate._drained.is_set()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        # The counter and its event are restored...
        assert gate._priority_waiters == 0
        assert gate._drained.is_set()
        # ...and background work is flowing again.
        resumed = len(stamps)
        await asyncio.sleep(FAST * 3)
        assert len(stamps) > resumed
    finally:
        await _stop_pack(hogs, stop)

    assert min(_gaps(stamps)) >= FAST * 0.9  # spacing survived the cancellation
