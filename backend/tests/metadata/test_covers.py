"""Cover cache: fetch via the shared limiter + egress + byte cap, host
allowlist, atomic write to disk (FRG-META-013)."""

from __future__ import annotations

import httpx
import pytest

from foragerr.http import HttpClientFactory
from foragerr.metadata.covers import cache_cover
from foragerr.metadata.errors import (
    ComicVineError,
    ComicVineUnavailable,
    CoverHostNotAllowed,
)
from cv_support import CV_HOST, _reset_gate  # noqa: F401
from http_support import PUBLIC_V4, NoConnectTransport, StubResolver, make_settings

JPEG = b"\xff\xd8\xff\xe0JFIF-bytes"


def _wire(tmp_path, handler, table, **overrides):
    settings = make_settings(
        tmp_path, comicvine_min_interval_seconds=0.05, **overrides
    )
    resolver = StubResolver(table)
    factory = HttpClientFactory(
        settings, resolver=resolver, transport=httpx.MockTransport(handler)
    )
    return settings, factory


@pytest.mark.req("FRG-META-013")
async def test_cover_downloaded_and_written_to_disk(tmp_path):
    settings, factory = _wire(
        tmp_path, lambda r: httpx.Response(200, content=JPEG), {CV_HOST: [PUBLIC_V4]}
    )
    dest = tmp_path / "covers" / "18166.jpg"
    ok = await cache_cover(
        f"https://{CV_HOST}/a/uploads/original/saga.jpg",
        dest,
        factory=factory,
        settings=settings,
    )
    assert ok is True
    assert dest.read_bytes() == JPEG
    assert not dest.with_name(dest.name + ".tmp").exists()  # atomic swap left no temp


@pytest.mark.req("FRG-META-013")
async def test_host_off_allowlist_is_refused_before_any_request(tmp_path):
    # NoConnectTransport asserts if any connection is attempted.
    settings = make_settings(tmp_path, comicvine_min_interval_seconds=0.05)
    factory = HttpClientFactory(
        settings,
        resolver=StubResolver({"evil.example": [PUBLIC_V4]}),
        transport=NoConnectTransport(),
    )
    with pytest.raises(CoverHostNotAllowed):
        await cache_cover(
            "https://evil.example/a/x.jpg",
            tmp_path / "c.jpg",
            factory=factory,
            settings=settings,
        )


@pytest.mark.req("FRG-META-013")
async def test_non_200_raises_unavailable(tmp_path):
    settings, factory = _wire(
        tmp_path, lambda r: httpx.Response(404), {CV_HOST: [PUBLIC_V4]}
    )
    with pytest.raises(ComicVineUnavailable):
        await cache_cover(
            f"https://{CV_HOST}/a/missing.jpg",
            tmp_path / "c.jpg",
            factory=factory,
            settings=settings,
        )


@pytest.mark.req("FRG-META-013")
async def test_allowlisted_host_still_subject_to_egress_policy(tmp_path):
    # host is on the allowlist but resolves to a private address -> egress
    # refusal surfaces as ComicVineUnavailable (SSRF defence still applies).
    settings, factory = _wire(
        tmp_path,
        lambda r: httpx.Response(200, content=JPEG),
        {CV_HOST: ["10.0.0.5"]},
    )
    with pytest.raises(ComicVineUnavailable):
        await cache_cover(
            f"https://{CV_HOST}/a/x.jpg",
            tmp_path / "c.jpg",
            factory=factory,
            settings=settings,
        )


@pytest.mark.req("FRG-META-013")
async def test_invalid_url_scheme_rejected(tmp_path):
    settings = make_settings(tmp_path, comicvine_min_interval_seconds=0.05)
    factory = HttpClientFactory(
        settings, resolver=StubResolver({}), transport=NoConnectTransport()
    )
    with pytest.raises(ComicVineError):
        await cache_cover(
            "ftp://comicvine.gamespot.com/x.jpg",
            tmp_path / "c.jpg",
            factory=factory,
            settings=settings,
        )
