"""Process-global rate limiter: serialized wire timing, clamp, 429/Retry-After
back-off, degraded flag (FRG-META-003, FRG-NFR-004)."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from foragerr.metadata import comicvine_degraded, comicvine_health
from foragerr.metadata.errors import ComicVineRateLimited
from foragerr.metadata.ratelimit import (
    MIN_INTERVAL_FLOOR,
    effective_interval,
)
from cv_support import _reset_gate, json_response, make_client  # noqa: F401
from fixtures import volume_envelope
from http_support import make_settings


@pytest.mark.req("FRG-META-003")
@pytest.mark.req("FRG-NFR-004")
async def test_concurrent_calls_serialize_to_the_min_interval(tmp_path):
    """Two concurrent CV calls must not burst: the second request reaches the
    wire at least one interval after the first (single process-global gate)."""
    interval = 0.4
    stamps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        stamps.append(time.monotonic())
        return json_response(volume_envelope())

    client, _ = make_client(
        tmp_path, handler, comicvine_min_interval_seconds=interval
    )
    async with client:
        await asyncio.gather(client.get_volume(1), client.get_volume(2))

    assert len(stamps) == 2
    spacing = abs(stamps[1] - stamps[0])
    assert spacing >= interval * 0.9, f"requests bursted: {spacing:.3f}s < {interval}s"


@pytest.mark.req("FRG-META-003")
@pytest.mark.req("FRG-NFR-004")
async def test_covers_share_the_same_gate_as_api_calls(tmp_path):
    """A cover fetch and an API call go through ONE gate — combined spacing,
    not per-call-site independent spacing."""
    from pathlib import Path

    from foragerr.http import HttpClientFactory
    from foragerr.metadata.comicvine import DEFAULT_BASE, ComicVineClient
    from foragerr.metadata.covers import cache_cover
    from cv_support import CV_HOST
    from http_support import PUBLIC_V4, StubResolver

    interval = 0.4
    stamps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        stamps.append(time.monotonic())
        if request.url.path.startswith("/a/uploads"):
            return httpx.Response(200, content=b"\xff\xd8\xffJPG")
        return json_response(volume_envelope())

    settings = make_settings(
        tmp_path, comicvine_api_key="k", comicvine_min_interval_seconds=interval
    )
    resolver = StubResolver({CV_HOST: [PUBLIC_V4]})
    factory = HttpClientFactory(
        settings, resolver=resolver, transport=httpx.MockTransport(handler)
    )
    client = ComicVineClient(settings, factory, base=DEFAULT_BASE)
    cover_url = "https://comicvine.gamespot.com/a/uploads/original/x.jpg"
    async with client:
        await asyncio.gather(
            client.get_volume(1),
            cache_cover(
                cover_url,
                Path(tmp_path) / "covers" / "1.jpg",
                factory=factory,
                settings=settings,
            ),
        )
    assert len(stamps) == 2
    assert abs(stamps[1] - stamps[0]) >= interval * 0.9


@pytest.mark.req("FRG-NFR-004")
def test_interval_below_floor_is_clamped(tmp_path):
    settings = make_settings(tmp_path, comicvine_min_interval_seconds=0.001)
    assert effective_interval(settings) == MIN_INTERVAL_FLOOR
    ok = make_settings(tmp_path, comicvine_min_interval_seconds=3.0)
    assert effective_interval(ok) == 3.0


@pytest.mark.req("FRG-META-003")
@pytest.mark.req("FRG-NFR-004")
async def test_429_retry_after_backs_off_and_flips_degraded(tmp_path):
    client, _ = make_client(
        tmp_path,
        lambda r: httpx.Response(429, headers={"retry-after": "1"}),
        comicvine_min_interval_seconds=0.25,
    )
    assert comicvine_degraded() is False
    async with client:
        with pytest.raises(ComicVineRateLimited):
            await client.get_volume(1)
    assert comicvine_degraded() is True
    health = comicvine_health()
    assert health["degraded"] is True
    assert health["cooldown_remaining_seconds"] >= 1.0


@pytest.mark.req("FRG-META-003")
async def test_degraded_clears_after_cooldown(tmp_path):
    from foragerr.metadata import ratelimit

    # A tiny synthetic back-off so the test doesn't wait seconds.
    gate = ratelimit.gate()
    gate.note_rate_limited(retry_after=0.15)
    assert comicvine_degraded() is True
    await asyncio.sleep(0.2)
    # acquire past the cool-down clears the flag
    await gate.acquire(0.0)
    assert comicvine_degraded() is False
