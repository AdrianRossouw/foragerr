"""Per-indexer request-spacing gate (FRG-IDX-008, FRG-NFR-005)."""

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
