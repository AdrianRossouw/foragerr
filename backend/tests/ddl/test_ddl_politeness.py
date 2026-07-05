"""Fetch politeness: spacing, jitter, persisted stats (FRG-DDL-006)."""

from __future__ import annotations

import datetime as dt

import pytest

from foragerr.ddl import politeness


@pytest.mark.req("FRG-DDL-006")
async def test_min_interval_clamped_to_floor_and_jitter_applied(tmp_path):
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    fixed = dt.datetime(2026, 7, 5, 12, 0, 0)
    # A configured interval below the floor is clamped UP to 15 s.
    first = await politeness.throttle(
        tmp_path, provider_id=1, min_interval=5,
        sleep=fake_sleep, clock=lambda: fixed, rand=lambda: 0.5,
    )
    second = await politeness.throttle(
        tmp_path, provider_id=1, min_interval=5,
        sleep=fake_sleep, clock=lambda: fixed, rand=lambda: 0.5,
    )
    jitter = 0.5 * politeness.JITTER_MAX_SECONDS
    assert waits[0] == pytest.approx(jitter)  # first fetch: only jitter
    # Second fetch, no wall-clock advance: full clamped interval + jitter.
    assert waits[1] == pytest.approx(politeness.MIN_INTERVAL_FLOOR + jitter)
    assert first.hits == 1 and second.hits == 2


@pytest.mark.req("FRG-DDL-006")
async def test_stats_persist_across_a_restart(tmp_path):
    fixed = dt.datetime(2026, 7, 5, 12, 0, 0)

    async def noop(_: float) -> None:
        return None

    await politeness.throttle(
        tmp_path, provider_id=7, min_interval=15,
        sleep=noop, clock=lambda: fixed, rand=lambda: 0.0,
    )
    # A fresh process re-reads the persisted stats (no in-memory carryover).
    reloaded = politeness.load_stats(tmp_path, 7)
    assert reloaded.hits == 1
    assert reloaded.last_run == fixed
