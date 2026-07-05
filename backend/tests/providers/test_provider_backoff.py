"""Generic per-provider back-off ladder (FRG-IDX-010, FRG-NFR-005)."""

from __future__ import annotations

import datetime as dt

import pytest

from foragerr.db import Database
from foragerr.providers.backoff import (
    FAST_FORWARD_MIN_LEVEL,
    LADDER,
    MAX_LEVEL,
    PROVIDER_DOWNLOAD_CLIENT,
    PROVIDER_INDEXER,
    ProviderBackoff,
)


class Clock:
    def __init__(self, start: dt.datetime) -> None:
        self.now = start

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + dt.timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    return Clock(dt.datetime(2026, 7, 5, 12, 0, 0))


@pytest.mark.req("FRG-IDX-010")
@pytest.mark.req("FRG-NFR-005")
async def test_consecutive_failures_escalate_the_ladder_and_skip(db, clock):
    backoff = ProviderBackoff(db, clock=clock)
    # Each failure steps one rung and sets a next-allowed time that skips it.
    for level in range(1, 5):
        status = await backoff.record_failure(
            PROVIDER_INDEXER, 7, reason="boom"
        )
        assert status.level == level
        assert status.active
        assert status.remaining_seconds == pytest.approx(
            LADDER[level].total_seconds(), rel=0.01
        )
    # Inside the window the provider is skipped; past it, eligible again.
    assert await backoff.is_backing_off(PROVIDER_INDEXER, 7)
    clock.advance(LADDER[4].total_seconds() + 1)
    assert not await backoff.is_backing_off(PROVIDER_INDEXER, 7)


@pytest.mark.req("FRG-IDX-010")
async def test_ladder_caps_at_24h(db, clock):
    backoff = ProviderBackoff(db, clock=clock)
    for _ in range(MAX_LEVEL + 5):
        status = await backoff.record_failure(PROVIDER_INDEXER, 1, reason="x")
    assert status.level == MAX_LEVEL
    assert status.remaining_seconds == pytest.approx(
        LADDER[MAX_LEVEL].total_seconds(), rel=0.01
    )


@pytest.mark.req("FRG-IDX-010")
@pytest.mark.req("FRG-NFR-005")
async def test_retry_after_and_auth_fast_forward_the_ladder(db, clock):
    backoff = ProviderBackoff(db, clock=clock)
    # Auth failure jumps to at least the fast-forward rung, not one step.
    status = await backoff.record_failure(
        PROVIDER_INDEXER, 2, reason="bad key", fast_forward=True
    )
    assert status.level == FAST_FORWARD_MIN_LEVEL
    assert status.remaining_seconds == pytest.approx(
        LADDER[FAST_FORWARD_MIN_LEVEL].total_seconds(), rel=0.01
    )

    # Retry-After floors the cool-down even beyond the ladder rung.
    status = await backoff.record_failure(
        PROVIDER_INDEXER, 3, reason="limit", retry_after=7200.0
    )
    assert status.remaining_seconds == pytest.approx(7200.0, rel=0.01)


@pytest.mark.req("FRG-IDX-010")
@pytest.mark.req("FRG-NFR-005")
async def test_success_resets_the_backoff(db, clock):
    backoff = ProviderBackoff(db, clock=clock)
    await backoff.record_failure(PROVIDER_INDEXER, 5, reason="x")
    await backoff.record_failure(PROVIDER_INDEXER, 5, reason="x")
    assert (await backoff.status(PROVIDER_INDEXER, 5)).active

    await backoff.record_success(PROVIDER_INDEXER, 5)
    status = await backoff.status(PROVIDER_INDEXER, 5)
    assert not status.active
    assert status.level == 0
    assert status.healthy


@pytest.mark.req("FRG-IDX-010")
async def test_ladder_is_generic_over_provider_type(db, clock):
    backoff = ProviderBackoff(db, clock=clock)
    await backoff.record_failure(PROVIDER_INDEXER, 1, reason="x")
    await backoff.record_failure(PROVIDER_DOWNLOAD_CLIENT, 1, reason="y")
    # Same numeric id, different provider_type — independent rows, no collision.
    assert (await backoff.status(PROVIDER_INDEXER, 1)).active
    assert (await backoff.status(PROVIDER_DOWNLOAD_CLIENT, 1)).active
    await backoff.record_success(PROVIDER_INDEXER, 1)
    assert not (await backoff.status(PROVIDER_INDEXER, 1)).active
    assert (await backoff.status(PROVIDER_DOWNLOAD_CLIENT, 1)).active


@pytest.mark.req("FRG-IDX-010")
async def test_health_surfaces_backing_off_providers(db, clock):
    backoff = ProviderBackoff(db, clock=clock)
    await backoff.record_failure(PROVIDER_INDEXER, 1, reason="x")
    await backoff.record_failure(PROVIDER_DOWNLOAD_CLIENT, 9, reason="y")
    all_health = await backoff.health()
    assert {(h.provider_type, h.provider_id) for h in all_health} == {
        (PROVIDER_INDEXER, 1),
        (PROVIDER_DOWNLOAD_CLIENT, 9),
    }
    only_indexers = await backoff.health(PROVIDER_INDEXER)
    assert [h.provider_id for h in only_indexers] == [1]


@pytest.mark.req("FRG-NFR-005")
async def test_backoff_state_survives_restart(migrated_dir, clock):
    db_path = migrated_dir / "foragerr.db"
    db1 = Database(db_path=db_path)
    try:
        backoff = ProviderBackoff(db1, clock=clock)
        await backoff.record_failure(PROVIDER_INDEXER, 4, reason="x")
        await backoff.record_failure(PROVIDER_INDEXER, 4, reason="x")
    finally:
        await db1.close()

    # A fresh Database over the same file = a process restart.
    db2 = Database(db_path=db_path)
    try:
        backoff2 = ProviderBackoff(db2, clock=clock)
        status = await backoff2.status(PROVIDER_INDEXER, 4)
        assert status.active
        assert status.level == 2
    finally:
        await db2.close()


@pytest.mark.req("FRG-IDX-010")
async def test_unknown_provider_is_healthy(db, clock):
    backoff = ProviderBackoff(db, clock=clock)
    status = await backoff.status(PROVIDER_INDEXER, 999)
    assert not status.active
    assert status.healthy
