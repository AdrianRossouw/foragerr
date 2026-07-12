"""Per-path hourly request budget with defer-and-resume (FRG-META-016).

The velocity gate (FRG-META-003) prevents bursts; this budget dimension prevents
the hour-scale per-path exhaustion the spacing math still permits (~1800/hour at
the 2 s default). Both dimensions ride the ONE process-global gate — a budget
refusal is a purely local decision that never flips the degraded/back-off state
and never blocks the caller. Health surfaces near-ceiling and exhausted buckets.

The rolling-window rollover is driven by manipulating the gate's documented
admission ledger (a deque of monotonic stamps) rather than sleeping an hour —
the honest test surface for the prune-at-3600 s behaviour.
"""

from __future__ import annotations

from collections import deque

import asyncio
import contextlib
import time

import httpx
import pytest

from foragerr.metadata import comicvine_degraded, comicvine_health, ratelimit
from foragerr.metadata.comicvine import DEFAULT_BASE, ComicVineClient
from foragerr.metadata.covers import cache_cover
from foragerr.metadata.errors import ComicVineBudgetExhausted
from foragerr.metadata.ratelimit import (
    BUDGET_CEILING,
    BUDGET_FLOOR,
    BUDGET_WINDOW_SECONDS,
    effective_budget,
)

from cv_support import CV_HOST, _reset_gate, json_response, make_client  # noqa: F401
from fixtures import volume_payload
from http_support import PUBLIC_V4, StubResolver, make_settings

from foragerr.http import HttpClientFactory


def _volume_envelope() -> object:
    return {"status_code": 1, "results": volume_payload()}


@pytest.mark.req("FRG-META-016")
async def test_exhausted_path_refuses_locally_without_touching_other_paths():
    """One path at its ceiling refuses the next same-path request with the typed
    error (no wire request, no degraded flip) while another path still admits."""
    gate = ratelimit.gate()
    budget = 3
    for _ in range(budget):
        await gate.acquire(0.0, bucket="volume", budget=budget)

    with pytest.raises(ComicVineBudgetExhausted) as excinfo:
        await gate.acquire(0.0, bucket="volume", budget=budget)
    assert excinfo.value.bucket == "volume"
    assert excinfo.value.retry_after_seconds > 0

    # The local refusal is NOT a rate-limit signal — degraded stays off.
    assert comicvine_degraded() is False

    # A different path bucket is unaffected and admits normally.
    await gate.acquire(0.0, bucket="issue", budget=budget)  # no raise


@pytest.mark.req("FRG-META-016")
async def test_refusal_is_immediate_even_while_the_gate_lock_is_held():
    """An exhausted-path caller is refused without queueing behind the gate
    lock — even while another caller holds the lock sleeping out a spacing
    interval (gate finding, cv-budget-caching review: the refusal check runs
    lock-free first, then re-runs under the lock as the authoritative
    admission decision)."""
    gate = ratelimit.gate()
    budget = 1
    # One admission sets the spacing clock and fills "volume" to its ceiling.
    await gate.acquire(0.0, bucket="volume", budget=budget)

    # A caller on ANOTHER bucket now holds the lock sleeping a long interval.
    sleeper = asyncio.create_task(
        gate.acquire(30.0, bucket="issue", budget=budget)
    )
    await asyncio.sleep(0.05)  # let it take the lock and start its sleep

    # The exhausted-path caller must be refused promptly, not after ~30 s.
    with pytest.raises(ComicVineBudgetExhausted):
        await asyncio.wait_for(
            gate.acquire(0.0, bucket="volume", budget=budget), timeout=1.0
        )

    sleeper.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await sleeper


@pytest.mark.req("FRG-META-016")
async def test_budget_refusal_does_not_flip_degraded():
    """A budget refusal must never mark ComicVine degraded (it is a local
    decision — the server saw nothing), distinct from a 429/ban back-off."""
    gate = ratelimit.gate()
    budget = 1
    await gate.acquire(0.0, bucket="search_api", budget=budget)
    with pytest.raises(ComicVineBudgetExhausted):
        await gate.acquire(0.0, bucket="search_api", budget=budget)
    health = comicvine_health()
    assert health["degraded"] is False
    assert health["cooldown_remaining_seconds"] == 0.0
    assert health["budget_exhausted"] is True


@pytest.mark.req("FRG-META-016")
async def test_window_rollover_readmits_after_stamps_age_out():
    """Admissions older than the rolling hour age out, so a previously exhausted
    path is admitted again automatically — no operator action."""
    gate = ratelimit.gate()
    budget = 2
    loop = asyncio.get_running_loop()
    now = loop.time()
    # A bucket filled to the ceiling but with every admission just over an hour
    # ago: the prune drops them, so capacity has returned.
    gate._ledgers["issue"] = deque(
        [now - BUDGET_WINDOW_SECONDS - 1.0, now - BUDGET_WINDOW_SECONDS - 0.5]
    )
    gate._budget = budget

    await gate.acquire(0.0, bucket="issue", budget=budget)  # no raise: stale pruned

    # The stale entries are gone and exactly one fresh admission is recorded.
    assert len(gate._ledgers["issue"]) == 1
    assert gate._ledgers["issue"][0] >= now


@pytest.mark.req("FRG-META-016")
async def test_health_payload_compact_then_populated_then_exhausted():
    """Quiet buckets stay out of the payload; a bucket crossing 80% appears with
    usage/ceiling/resume; at the ceiling the exhausted flag flips."""
    gate = ratelimit.gate()
    budget = 10

    # Below the 80% warning threshold: compact payload, no path entries.
    for _ in range(5):
        await gate.acquire(0.0, bucket="issue", budget=budget)
    health = comicvine_health()
    assert health["path_budgets"] == {}
    assert health["budget_exhausted"] is False

    # Cross 80% (8/10): the bucket appears with its usage and ceiling.
    for _ in range(3):
        await gate.acquire(0.0, bucket="issue", budget=budget)
    health = comicvine_health()
    assert set(health["path_budgets"]) == {"issue"}
    assert health["path_budgets"]["issue"]["used"] == 8
    assert health["path_budgets"]["issue"]["ceiling"] == 10
    assert health["path_budgets"]["issue"]["resumes_in_seconds"] == 0.0
    assert health["budget_exhausted"] is False

    # At the ceiling (10/10): exhausted flag on, resume time positive.
    for _ in range(2):
        await gate.acquire(0.0, bucket="issue", budget=budget)
    health = comicvine_health()
    assert health["budget_exhausted"] is True
    assert health["path_budgets"]["issue"]["used"] == 10
    assert health["path_budgets"]["issue"]["resumes_in_seconds"] > 0.0


@pytest.mark.req("FRG-META-016")
async def test_health_payload_returns_to_compact_after_window_rolls():
    """Once every admission ages out, the payload returns to its compact form."""
    gate = ratelimit.gate()
    budget = 4
    for _ in range(budget):
        await gate.acquire(0.0, bucket="issue", budget=budget)
    assert comicvine_health()["budget_exhausted"] is True

    # Age every admission past the window; the next health read prunes them.
    loop = asyncio.get_running_loop()
    old = loop.time() - BUDGET_WINDOW_SECONDS - 1.0
    gate._ledgers["issue"] = deque([old] * budget)
    health = comicvine_health()
    assert health["path_budgets"] == {}
    assert health["budget_exhausted"] is False


@pytest.mark.req("FRG-META-016")
def test_ceiling_configuration_is_clamped(tmp_path):
    """A budget above 200 or below the floor is clamped into the documented
    bounds rather than accepted as an unsafe value."""
    over = make_settings(tmp_path, comicvine_hourly_path_budget=1000)
    assert effective_budget(over) == BUDGET_CEILING
    under = make_settings(tmp_path, comicvine_hourly_path_budget=1)
    assert effective_budget(under) == BUDGET_FLOOR
    ok = make_settings(tmp_path, comicvine_hourly_path_budget=150)
    assert effective_budget(ok) == 150


@pytest.mark.req("FRG-META-016")
@pytest.mark.req("FRG-META-003")
async def test_every_wire_request_consumes_exactly_one_budget_unit_covers_included(
    tmp_path,
):
    """Both dimensions gate one request exactly once: a get_volume and a cover
    fetch each consume exactly one unit of their bucket through the single gate —
    there is no second gate or budget bypass, covers included."""
    from pathlib import Path

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/a/uploads"):
            return httpx.Response(200, content=b"\xff\xd8\xffJPG")
        return json_response(_volume_envelope())

    settings = make_settings(
        tmp_path,
        comicvine_api_key="k",
        comicvine_min_interval_seconds=0.25,
        comicvine_hourly_path_budget=150,
    )
    resolver = StubResolver({CV_HOST: [PUBLIC_V4]})
    factory = HttpClientFactory(
        settings, resolver=resolver, transport=httpx.MockTransport(handler)
    )
    client = ComicVineClient(settings, factory, base=DEFAULT_BASE)
    cover_url = "https://comicvine.gamespot.com/a/uploads/original/x.jpg"
    async with client:
        await client.get_volume(18166)
        await cache_cover(
            cover_url,
            Path(tmp_path) / "covers" / "1.jpg",
            factory=factory,
            settings=settings,
        )

    gate = ratelimit.gate()
    # Exactly one admission on the volume bucket, exactly one on the covers bucket.
    assert len(gate._ledgers["volume"]) == 1
    assert len(gate._ledgers["covers"]) == 1


@pytest.mark.req("FRG-META-016")
@pytest.mark.req("FRG-NFR-004")
async def test_client_request_raises_typed_budget_error_at_ceiling(tmp_path):
    """Through the real client: once a path is at its (tiny configured) ceiling,
    the next request on it raises the typed error before reaching the wire."""
    stamps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        stamps.append(time.monotonic())
        return json_response(_volume_envelope())

    client, transport = make_client(
        tmp_path,
        handler,
        comicvine_min_interval_seconds=0.25,
        comicvine_hourly_path_budget=10,  # clamps UP to the floor of 10
    )
    async with client:
        # The floor is 10, so ten volume-path requests admit, the eleventh refuses.
        for _ in range(10):
            await client.get_volume(18166)
        with pytest.raises(ComicVineBudgetExhausted) as excinfo:
            await client.get_volume(18166)

    assert excinfo.value.bucket == "volume"
    # The refused request never reached the transport.
    assert len(transport.requests) == 10
