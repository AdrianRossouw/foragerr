"""The Humble order-API client: fixture-driven parse, hardening, auth mapping,
politeness, and bounded requests (FRG-SRC-002/003, FRG-NFR-005/006)."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from foragerr.sources import ratelimit
from foragerr.sources.humble import (
    ORDER_LIST_MAX_BYTES,
    HumbleAuthError,
    HumbleClient,
    HumbleMalformedError,
    HumbleUnavailable,
    parse_order,
)
from sources_support import (  # noqa: F401 - shared helpers
    fixture_bytes,
    make_factory,
    order_handler,
)

GAMEKEY = "aBcD1234synthetic"


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


def _client(config_dir: Path, handler, *, min_interval: float = 0.0) -> HumbleClient:
    factory = make_factory(config_dir, httpx.MockTransport(handler))
    return HumbleClient(factory, "SYNTHETIC_COOKIE", source_id=1, min_interval=min_interval)


@pytest.mark.req("FRG-SRC-003")
async def test_list_gamekeys_parses_fixture(config_dir):
    handler = order_handler(list_body=fixture_bytes("order_list.json"))
    async with _client(config_dir, handler) as client:
        keys = await client.list_gamekeys()
    assert keys == ["aBcD1234synthetic", "eFgH5678synthetic"]


@pytest.mark.req("FRG-SRC-003")
async def test_fetch_order_classifies_and_skips_malformed(config_dir):
    handler = order_handler(
        order_bodies={GAMEKEY: fixture_bytes("order_comics.json")}
    )
    async with _client(config_dir, handler) as client:
        ents = await client.fetch_order(GAMEKEY)

    by_name = {e.machine_name: e for e in ents}
    # The malformed subproduct (no machine_name) was skipped, not raised.
    assert "synth_singleissue_01" in by_name
    assert len(ents) == 6  # 7 subproducts, 1 malformed skipped

    twins = by_name["synth_singleissue_01"]
    assert twins.classification == "comic"
    assert twins.preferred is not None and twins.preferred.format == "CBZ"
    # md5/size ride from the preferred (CBZ) option.
    assert twins.preferred.md5 == "0123456789abcdef0123456789abcdef"
    assert twins.preferred.file_size == 41943040
    assert twins.publisher == "Synthetic Comics"

    assert by_name["synth_collected_edition_vol1"].classification == "comic"
    assert by_name["synth_prose_novel_epub_only"].classification == "other"
    assert by_name["synth_video_game_title"].classification == "other"
    assert by_name["synth_artbook_pdf_only"].classification == "comic"
    assert by_name["synth_prose_with_pdf_twin"].classification == "other"


@pytest.mark.req("FRG-SRC-003")
def test_parse_order_skips_bad_md5_and_size():
    body = (
        b'{"gamekey":"g","subproducts":[{"machine_name":"m","human_name":"n",'
        b'"downloads":[{"platform":"ebook","download_struct":[{"name":"CBZ",'
        b'"md5":"not-a-real-md5","file_size":-5,'
        b'"url":{"web":"https://dl.humble.com/x.cbz?sig=REDACTED"}}]}]}]}'
    )
    ents = parse_order("g", body)
    assert len(ents) == 1
    opt = ents[0].preferred
    assert opt.format == "CBZ"  # from the .cbz extension
    assert opt.md5 is None  # bad md5 dropped
    assert opt.file_size is None  # negative size dropped


@pytest.mark.req("FRG-SRC-002")
async def test_401_maps_to_auth_error(config_dir):
    handler = order_handler(list_status=401, list_body=b"{}")
    async with _client(config_dir, handler) as client:
        with pytest.raises(HumbleAuthError):
            await client.list_gamekeys()


@pytest.mark.req("FRG-SRC-002")
async def test_403_maps_to_auth_error(config_dir):
    handler = order_handler(list_status=403, list_body=b"{}")
    async with _client(config_dir, handler) as client:
        with pytest.raises(HumbleAuthError):
            await client.list_gamekeys()


@pytest.mark.req("FRG-SRC-003")
async def test_5xx_maps_to_unavailable(config_dir):
    handler = order_handler(list_status=503, list_body=b"{}")
    async with _client(config_dir, handler) as client:
        with pytest.raises(HumbleUnavailable):
            await client.list_gamekeys()


@pytest.mark.req("FRG-SRC-003")
async def test_malformed_body_raises(config_dir):
    handler = order_handler(list_body=b"not json at all")
    async with _client(config_dir, handler) as client:
        with pytest.raises(HumbleMalformedError):
            await client.list_gamekeys()


@pytest.mark.req("FRG-NFR-006")
async def test_oversize_response_is_bounded(config_dir):
    # A body beyond the client's byte cap aborts with a bounded error rather
    # than being buffered — surfaced as a transient failure, never a crash.
    big = b" " * (ORDER_LIST_MAX_BYTES + 1024)
    handler = order_handler(list_body=big)
    async with _client(config_dir, handler) as client:
        with pytest.raises(HumbleUnavailable):
            await client.list_gamekeys()


@pytest.mark.req("FRG-SRC-002")
async def test_cookie_sent_as_simpleauth_sess(config_dir):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("cookie", ""))
        return httpx.Response(200, content=b"[]")

    async with _client(config_dir, handler) as client:
        await client.list_gamekeys()
    assert seen == ["_simpleauth_sess=SYNTHETIC_COOKIE"]


@pytest.mark.req("FRG-NFR-005")
async def test_requests_are_spaced_per_source(config_dir):
    handler = order_handler(list_body=b"[]")
    async with _client(config_dir, handler, min_interval=0.2) as client:
        start = time.monotonic()
        await client.list_gamekeys()
        await client.list_gamekeys()
        elapsed = time.monotonic() - start
    # Two requests to the same source are spaced by at least the min interval.
    assert elapsed >= 0.2
