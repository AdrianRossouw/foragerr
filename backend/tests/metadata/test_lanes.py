"""Batch and interactive priority lanes within one key (FRG-META-022).

The lane is a THIRD dimension on the one process-global gate, beside velocity
(FRG-META-003) and the per-path hourly budget (FRG-META-016) — never a second
gate and never a second key. Background work is capped at a configurable share
of each path budget so an interactive reserve always exists; interactive work
may spend the whole path budget. The FRG-META-016 semantics are unchanged in
shape: a refusal is local (never degraded), never blocks, is always logged, and
carries an honest resume time — which for a lane-scoped refusal is derived from
the same one ledger the whole-path view is derived from.

Ledger stamps are constructed directly where a test needs a known window
position: the alternative is sleeping out an hour to observe the prune.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from pathlib import Path

import httpx
import pytest

from foragerr.config import Settings
from foragerr.http import HttpClientFactory
from foragerr.metadata import comicvine_degraded, comicvine_health, ratelimit
from foragerr.metadata.comicvine import DEFAULT_BASE, ComicVineClient
from foragerr.metadata.covers import COVER_BUDGET_BUCKET, cache_cover
from foragerr.metadata.errors import ComicVineBudgetExhausted
from foragerr.metadata.ratelimit import (
    BATCH_SHARE_CEILING,
    BATCH_SHARE_FLOOR,
    BUDGET_WINDOW_SECONDS,
    LANE_BATCH,
    LANE_INTERACTIVE,
    _Stamp,
    _lane_of,
    batch_ceiling,
    effective_batch_share,
)

from cv_support import CV_HOST, _reset_gate, json_response, make_client  # noqa: F401
from fixtures import volume_payload
from http_support import PUBLIC_V4, StubResolver, make_settings


def _volume_envelope() -> object:
    return {"status_code": 1, "results": volume_payload()}


def _seed(bucket: str, entries: list[tuple[float, str]], *, budget: int, share: float):
    """Install a lane-tagged ledger for ``bucket`` (descending offsets, seconds
    ago, so the deque stays oldest-first) and remember the ceiling/share the
    health snapshot reports against."""
    gate = ratelimit.gate()
    now = asyncio.get_running_loop().time()
    gate._ledgers[bucket] = deque(
        _Stamp(now - ago, lane) for ago, lane in entries
    )
    gate._budget = budget
    gate._batch_share = share
    return gate, now


# -- admission ------------------------------------------------------------


@pytest.mark.req("FRG-META-022")
async def test_batch_pauses_first_while_interactive_keeps_a_reserve():
    """With the batch share of a path spent, a batch caller is refused with a
    lane-naming typed error while an interactive caller is admitted from the
    reserve — and the refusal stays a local decision (never degraded)."""
    gate = ratelimit.gate()
    budget, share = 10, 0.5  # batch ceiling 5, interactive reserve 5
    for _ in range(5):
        await gate.acquire(0.0, bucket="volume", budget=budget, batch_share=share)

    with pytest.raises(ComicVineBudgetExhausted) as excinfo:
        await gate.acquire(
            0.0,
            bucket="volume",
            budget=budget,
            lane=LANE_BATCH,
            batch_share=share,
        )
    refusal = excinfo.value
    assert refusal.lane == LANE_BATCH
    assert refusal.bucket == "volume"
    assert refusal.retry_after_seconds > 0
    assert "batch share of path 'volume' exhausted" in str(refusal)
    assert "interactive reserve remains" in str(refusal)

    # The interactive lane is admitted from the reserve the pause protects.
    await gate.acquire(
        0.0,
        bucket="volume",
        budget=budget,
        lane=LANE_INTERACTIVE,
        batch_share=share,
    )
    assert len(gate._ledgers["volume"]) == 6

    # FRG-META-016 non-regression: a lane refusal is not a rate-limit signal.
    assert comicvine_degraded() is False
    assert comicvine_health()["budget_exhausted"] is False


@pytest.mark.req("FRG-META-022")
@pytest.mark.req("FRG-META-016")
async def test_interactive_alone_exhausts_at_the_full_ceiling():
    """The reserve is a floor for interactivity, never an allowance beyond the
    path ceiling: interactive traffic alone stops at the full budget with the
    unchanged FRG-META-016 refusal (no lane named — nothing is reserved)."""
    gate = ratelimit.gate()
    budget, share = 6, 0.5
    for _ in range(budget):
        await gate.acquire(
            0.0,
            bucket="volume",
            budget=budget,
            lane=LANE_INTERACTIVE,
            batch_share=share,
        )

    with pytest.raises(ComicVineBudgetExhausted) as excinfo:
        await gate.acquire(
            0.0,
            bucket="volume",
            budget=budget,
            lane=LANE_INTERACTIVE,
            batch_share=share,
        )
    refusal = excinfo.value
    assert refusal.lane is None
    assert "comicvine hourly budget exhausted for path 'volume'" in str(refusal)
    assert refusal.retry_after_seconds > 0
    assert comicvine_degraded() is False
    assert comicvine_health()["budget_exhausted"] is True


@pytest.mark.req("FRG-META-022")
async def test_unclassified_caller_is_accounted_as_batch():
    """An acquire that declares no lane spends batch capacity — a background
    job added without lane awareness degrades itself, not the operator."""
    gate = ratelimit.gate()
    budget, share = 8, 0.5  # batch ceiling 4
    for _ in range(4):
        await gate.acquire(0.0, bucket="issue", budget=budget, batch_share=share)

    assert [_lane_of(s) for s in gate._ledgers["issue"]] == [LANE_BATCH] * 4

    with pytest.raises(ComicVineBudgetExhausted) as excinfo:
        await gate.acquire(0.0, bucket="issue", budget=budget, batch_share=share)
    assert excinfo.value.lane == LANE_BATCH

    # ... while the interactive reserve it left alone is still spendable.
    await gate.acquire(
        0.0,
        bucket="issue",
        budget=budget,
        lane=LANE_INTERACTIVE,
        batch_share=share,
    )


@pytest.mark.req("FRG-META-022")
async def test_an_unknown_lane_label_is_accounted_as_batch():
    """Fail-frugal coercion: a typo'd/unknown lane can never open the reserve."""
    gate = ratelimit.gate()
    budget, share = 8, 0.5
    for _ in range(4):
        await gate.acquire(
            0.0, bucket="issue", budget=budget, lane="urgent", batch_share=share
        )
    assert [_lane_of(s) for s in gate._ledgers["issue"]] == [LANE_BATCH] * 4
    with pytest.raises(ComicVineBudgetExhausted):
        await gate.acquire(
            0.0, bucket="issue", budget=budget, lane="urgent", batch_share=share
        )


@pytest.mark.req("FRG-META-022")
@pytest.mark.req("FRG-META-016")
async def test_without_a_share_the_lane_dimension_is_off():
    """Omitting ``batch_share`` leaves admission exactly as FRG-META-016 had it
    (the same optional-dimension idiom as bucket/budget): batch may spend the
    whole path budget."""
    gate = ratelimit.gate()
    budget = 4
    for _ in range(budget):
        await gate.acquire(0.0, bucket="volume", budget=budget)
    with pytest.raises(ComicVineBudgetExhausted) as excinfo:
        await gate.acquire(0.0, bucket="volume", budget=budget)
    assert excinfo.value.lane is None


# -- resume math ----------------------------------------------------------


@pytest.mark.req("FRG-META-022")
async def test_lane_scoped_retry_after_tracks_the_oldest_batch_stamp():
    """A lane-scoped refusal resumes when the batch count drops below the
    share — i.e. when the oldest batch stamp ages out of the window — even
    though newer interactive stamps sit in the same ledger."""
    budget, share = 10, 0.5  # batch ceiling 5
    gate, now = _seed(
        "volume",
        [
            (3000.0, LANE_BATCH),
            (2000.0, LANE_BATCH),
            (1000.0, LANE_BATCH),
            (500.0, LANE_BATCH),
            (200.0, LANE_BATCH),
            (100.0, LANE_INTERACTIVE),
            (50.0, LANE_INTERACTIVE),
        ],
        budget=budget,
        share=share,
    )

    with pytest.raises(ComicVineBudgetExhausted) as excinfo:
        await gate.acquire(
            0.0,
            bucket="volume",
            budget=budget,
            lane=LANE_BATCH,
            batch_share=share,
        )
    refusal = excinfo.value
    assert refusal.lane == LANE_BATCH
    # The oldest BATCH stamp (3000 s ago) must age out at 3600 s.
    assert refusal.retry_after_seconds == pytest.approx(
        BUDGET_WINDOW_SECONDS - 3000.0, abs=1.0
    )
    # Total is 7/10, so the whole-path view alone would say "resume now".
    assert len(gate._ledgers["volume"]) == 7


@pytest.mark.req("FRG-META-022")
async def test_batch_retry_after_waits_for_both_constraints():
    """When the path ceiling AND the batch share both bind, batch resumes only
    once BOTH hold — the later of the two age-out times, not the first."""
    budget, share = 5, 0.5  # batch ceiling 2, path ceiling 5
    gate, now = _seed(
        "volume",
        [
            (3500.0, LANE_INTERACTIVE),
            (3400.0, LANE_INTERACTIVE),
            (100.0, LANE_BATCH),
            (50.0, LANE_BATCH),
            (40.0, LANE_INTERACTIVE),
        ],
        budget=budget,
        share=share,
    )

    with pytest.raises(ComicVineBudgetExhausted) as excinfo:
        await gate.acquire(
            0.0,
            bucket="volume",
            budget=budget,
            lane=LANE_BATCH,
            batch_share=share,
        )
    refusal = excinfo.value
    # The path clears in ~100 s (the 3500 s-old stamp ages out) but the batch
    # share does not clear until the 100 s-old batch stamp does, at ~3500 s.
    assert refusal.retry_after_seconds == pytest.approx(
        BUDGET_WINDOW_SECONDS - 100.0, abs=1.0
    )
    # Whole-path exhaustion refuses every lane, so the message is the
    # unchanged FRG-META-016 one (nothing is reserved for anyone).
    assert refusal.lane is None

    # An interactive caller sees only the whole-path constraint.
    with pytest.raises(ComicVineBudgetExhausted) as interactive:
        await gate.acquire(
            0.0,
            bucket="volume",
            budget=budget,
            lane=LANE_INTERACTIVE,
            batch_share=share,
        )
    assert interactive.value.retry_after_seconds == pytest.approx(
        BUDGET_WINDOW_SECONDS - 3500.0, abs=1.0
    )


@pytest.mark.req("FRG-META-022")
async def test_a_zero_batch_ceiling_refuses_cleanly():
    """Defensive: a budget so small that the share rounds the batch ceiling to
    zero (unreachable above the documented budget floor) refuses batch with an
    honest window-length resume rather than crashing, and still admits
    interactive."""
    gate = ratelimit.gate()
    budget, share = 1, 0.5  # batch ceiling floor(0.5) == 0
    with pytest.raises(ComicVineBudgetExhausted) as excinfo:
        await gate.acquire(0.0, bucket="volume", budget=budget, batch_share=share)
    assert excinfo.value.lane == LANE_BATCH
    assert excinfo.value.retry_after_seconds == BUDGET_WINDOW_SECONDS
    await gate.acquire(
        0.0,
        bucket="volume",
        budget=budget,
        lane=LANE_INTERACTIVE,
        batch_share=share,
    )


@pytest.mark.req("FRG-META-022")
async def test_every_lane_deferral_is_logged(caplog):
    """A deferral is never silent — the log line names the lane."""
    gate = ratelimit.gate()
    budget, share = 10, 0.5
    for _ in range(5):
        await gate.acquire(0.0, bucket="volume", budget=budget, batch_share=share)
    with caplog.at_level(logging.WARNING, logger="foragerr.metadata.ratelimit"):
        with pytest.raises(ComicVineBudgetExhausted):
            await gate.acquire(
                0.0, bucket="volume", budget=budget, batch_share=share
            )
    assert any(
        "batch share exhausted for path 'volume'" in record.getMessage()
        for record in caplog.records
    )


# -- configuration --------------------------------------------------------


@pytest.mark.req("FRG-META-022")
def test_batch_share_configuration_is_clamped(tmp_path, caplog):
    """A share below 0.30 (background starves) or above 0.95 (the reserve stops
    being a reserve) is clamped into the documented bounds with a warning."""
    with caplog.at_level(logging.WARNING, logger="foragerr.metadata.ratelimit"):
        under = make_settings(tmp_path, comicvine_batch_budget_share=0.2)
        assert effective_batch_share(under) == BATCH_SHARE_FLOOR
        over = make_settings(tmp_path, comicvine_batch_budget_share=0.99)
        assert effective_batch_share(over) == BATCH_SHARE_CEILING
    warnings = [r.getMessage() for r in caplog.records]
    assert sum("comicvine_batch_budget_share" in m for m in warnings) == 2

    ok = make_settings(tmp_path, comicvine_batch_budget_share=0.5)
    assert effective_batch_share(ok) == 0.5


@pytest.mark.req("FRG-META-022")
def test_batch_share_defaults_to_seventy_percent(tmp_path):
    settings = make_settings(tmp_path)
    assert effective_batch_share(settings) == 0.70
    assert batch_ceiling(150, effective_batch_share(settings)) == 105


@pytest.mark.req("FRG-META-022")
def test_exactly_one_comicvine_key_is_configurable():
    """The one-key non-goal, pinned on the configuration surface: there is a
    single ComicVine credential setting and no plural/pool/rotation surface to
    split one operator's traffic across keys."""
    key_fields = [
        name
        for name in Settings.model_fields
        if "comicvine" in name and "key" in name
    ]
    assert key_fields == ["comicvine_api_key"]
    for name in Settings.model_fields:
        lowered = name.lower()
        assert "api_keys" not in lowered
        assert not ("comicvine" in lowered and "keys" in lowered)


# -- health ---------------------------------------------------------------


@pytest.mark.req("FRG-META-022")
@pytest.mark.req("FRG-META-016")
async def test_health_payload_carries_batch_numbers_additively():
    """The per-bucket entry gains batch_used/batch_ceiling beside the existing
    used/ceiling/resumes_in_seconds — and a bucket whose BATCH lane is paused
    is reported even below the 80% warning fraction, so an operator can see why
    background work stopped."""
    gate = ratelimit.gate()
    budget, share = 10, 0.7  # batch ceiling 7, warning threshold 8
    for _ in range(7):
        await gate.acquire(0.0, bucket="volume", budget=budget, batch_share=share)

    health = comicvine_health()
    entry = health["path_budgets"]["volume"]
    assert entry["used"] == 7
    assert entry["ceiling"] == 10
    assert entry["batch_used"] == 7
    assert entry["batch_ceiling"] == 7
    assert entry["resumes_in_seconds"] == 0.0
    assert health["budget_exhausted"] is False

    # Interactive spend counts against the path but never against the batch
    # share, and the whole-path keys keep their original meaning.
    await gate.acquire(
        0.0,
        bucket="volume",
        budget=budget,
        lane=LANE_INTERACTIVE,
        batch_share=share,
    )
    entry = comicvine_health()["path_budgets"]["volume"]
    assert entry["used"] == 8
    assert entry["batch_used"] == 7


# -- the client seam ------------------------------------------------------


@pytest.mark.req("FRG-META-022")
async def test_client_lane_is_applied_to_every_fetch(tmp_path):
    """Lane is declared once at construction and applied by _fetch: a batch
    client stops at its share while an interactive client keeps working on the
    same path through the same gate."""
    handler = lambda request: json_response(_volume_envelope())  # noqa: E731
    overrides = {
        "comicvine_min_interval_seconds": 0.25,
        "comicvine_hourly_path_budget": 10,  # the documented floor
        "comicvine_batch_budget_share": 0.30,  # batch ceiling 3
    }
    batch_client, transport = make_client(tmp_path, handler, **overrides)
    interactive_client, _ = make_client(
        tmp_path, handler, lane=LANE_INTERACTIVE, **overrides
    )

    async with batch_client, interactive_client:
        for _ in range(3):
            await batch_client.get_volume(18166)
        with pytest.raises(ComicVineBudgetExhausted) as excinfo:
            await batch_client.get_volume(18166)
        # The operator's client is unaffected — that is the whole point.
        await interactive_client.get_volume(18166)

    assert excinfo.value.lane == LANE_BATCH
    assert len(transport.requests) == 3  # the refused batch call never flew
    lanes = [_lane_of(s) for s in ratelimit.gate()._ledgers["volume"]]
    assert lanes == [LANE_BATCH] * 3 + [LANE_INTERACTIVE]


@pytest.mark.req("FRG-META-022")
async def test_client_lane_defaults_to_batch(tmp_path):
    """An un-laned client construction is batch — the fail-frugal default."""
    client, _ = make_client(
        tmp_path, lambda request: json_response(_volume_envelope())
    )
    async with client:
        assert client._lane == LANE_BATCH


@pytest.mark.req("FRG-META-022")
async def test_cover_caching_spends_the_batch_lane(tmp_path):
    """Cover caching is background work: it spends batch capacity explicitly,
    never the interactive reserve."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\xff\xd8\xffJPG")

    settings = make_settings(
        tmp_path,
        comicvine_api_key="k",
        comicvine_min_interval_seconds=0.25,
        comicvine_batch_budget_share=0.5,
    )
    resolver = StubResolver({CV_HOST: [PUBLIC_V4]})
    factory = HttpClientFactory(
        settings, resolver=resolver, transport=httpx.MockTransport(handler)
    )
    await cache_cover(
        "https://comicvine.gamespot.com/a/uploads/original/x.jpg",
        Path(tmp_path) / "covers" / "1.jpg",
        factory=factory,
        settings=settings,
    )

    ledger = ratelimit.gate()._ledgers[COVER_BUDGET_BUCKET]
    assert [_lane_of(s) for s in ledger] == [LANE_BATCH]
    # ... and the share it was admitted against is the configured one.
    assert ratelimit.gate()._batch_share == 0.5


@pytest.mark.req("FRG-META-022")
async def test_the_lane_rides_the_one_gate(tmp_path):
    """There is still exactly ONE process-global gate — the lane is a third
    dimension on it, not a second gate (FRG-META-003 amendment shape): two
    clients on different lanes queue on the same gate object."""
    assert ratelimit.gate() is ratelimit.gate()
    settings = make_settings(tmp_path, comicvine_api_key="k")
    resolver = StubResolver({CV_HOST: [PUBLIC_V4]})
    factory = HttpClientFactory(
        settings,
        resolver=resolver,
        transport=httpx.MockTransport(
            lambda request: json_response(_volume_envelope())
        ),
    )
    batch = ComicVineClient(settings, factory, base=DEFAULT_BASE)
    interactive = ComicVineClient(
        settings, factory, base=DEFAULT_BASE, lane=LANE_INTERACTIVE
    )
    async with batch, interactive:
        assert batch._lane == LANE_BATCH
        assert interactive._lane == LANE_INTERACTIVE
        await batch.get_volume(18166)
        await interactive.get_volume(18166)
    # Both admissions landed in the ONE ledger, distinguishable by lane.
    ledger = ratelimit.gate()._ledgers["volume"]
    assert [_lane_of(s) for s in ledger] == [LANE_BATCH, LANE_INTERACTIVE]
