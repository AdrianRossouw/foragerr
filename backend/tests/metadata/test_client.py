"""ComicVine client fundamentals + typed error mapping + key redaction
(FRG-META-001, FRG-META-002)."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from foragerr import logging as flog
from foragerr.http import HttpClientFactory
from foragerr.logging import setup_logging
from foragerr.metadata import comicvine_degraded
from foragerr.metadata.comicvine import DEFAULT_BASE, ComicVineClient
from foragerr.metadata.errors import (
    ComicVineAuthError,
    ComicVineMalformedResponse,
    ComicVineRateLimited,
    ComicVineUnavailable,
)
from cv_support import CV_HOST, _reset_gate, json_response, make_client  # noqa: F401
from fixtures import (
    BAN_PAGE_HTML,
    issue_payload,
    issues_envelope,
    search_envelope,
    volume_envelope,
    volume_payload,
)
from http_support import (
    PUBLIC_V4,
    StubResolver,
    fixture_server,
    make_settings,
)


# --- request shape (FRG-META-001) -------------------------------------------


@pytest.mark.req("FRG-META-001")
async def test_request_carries_json_field_list_and_honest_user_agent(tmp_path):
    client, transport = make_client(tmp_path, lambda r: json_response(volume_envelope()))
    async with client:
        await client.get_volume(18166)
    req = transport.requests[-1]
    assert req.url.host == CV_HOST
    assert req.url.path.startswith("/api/volume/4050-18166")
    assert req.url.params["format"] == "json"
    assert req.url.params["field_list"]  # per-endpoint minimised list
    assert req.url.params["api_key"] == "CV-SECRET-KEY-abc123"
    assert req.headers["user-agent"].startswith("foragerr/")
    # never requests XML
    assert "xml" not in req.url.query.decode().lower()


@pytest.mark.req("FRG-CRTR-001")
async def test_get_issue_credits_hits_detail_endpoint_and_maps(tmp_path):
    """The credit source is the issue DETAIL endpoint (``issue/4000-{id}/``)
    with a minimal person_credits field list; the client maps + normalizes the
    payload exactly as the opportunistic list path would, through the gate."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return json_response(
            {
                "status_code": 1,
                "results": {
                    "id": 42,
                    "person_credits": [
                        {"id": 10, "name": "Alice", "role": "writer, penciller"},
                        {"id": 11, "name": "Bob", "role": "inker"},
                    ],
                },
            }
        )

    client, transport = make_client(tmp_path, _handler)
    async with client:
        credits = await client.get_issue_credits(42)

    req = transport.requests[-1]
    assert req.url.path.startswith("/api/issue/4000-42")
    assert req.url.params["field_list"] == "id,person_credits"
    assert req.url.params["api_key"] == "CV-SECRET-KEY-abc123"
    # Compound role split + normalized; verbatim retained.
    got = {(c.cv_person_id, c.role_normalized) for c in credits}
    assert got == {(10, "writer"), (10, "penciler"), (11, "inker")}


@pytest.mark.req("FRG-CRTR-001")
async def test_get_issue_credits_missing_results_is_malformed(tmp_path):
    client, _ = make_client(
        tmp_path, lambda r: json_response({"status_code": 1, "results": None})
    )
    async with client:
        with pytest.raises(ComicVineMalformedResponse):
            await client.get_issue_credits(1)


@pytest.mark.req("FRG-CRTR-001")
async def test_get_issue_credits_5xx_raises_unavailable(tmp_path):
    client, _ = make_client(tmp_path, lambda r: httpx.Response(503))
    async with client:
        with pytest.raises(ComicVineUnavailable):
            await client.get_issue_credits(1)


@pytest.mark.req("FRG-META-001")
async def test_hung_connection_fails_within_read_timeout(tmp_path):
    async def hang(reader, writer):
        await reader.read()  # accept, then never respond

    async with fixture_server(hang) as base_url:
        port = base_url.rsplit(":", 1)[1]
        settings = make_settings(
            tmp_path,
            comicvine_api_key="k",
            comicvine_min_interval_seconds=0.25,
            http_read_timeout_seconds=0.3,
        )
        resolver = StubResolver({CV_HOST: ["127.0.0.1"]})
        factory = HttpClientFactory(
            settings, resolver=resolver, test_allow_addresses=["127.0.0.1"]
        )
        client = ComicVineClient(
            settings, factory, base=f"http://127.0.0.1:{port}/api"
        )
        started = time.monotonic()
        async with client:
            with pytest.raises(ComicVineUnavailable):
                await client.get_volume(1)
        assert time.monotonic() - started < 3.0  # bounded by the 0.3s read timeout


@pytest.mark.req("FRG-META-001")
async def test_401_maps_to_auth_error(tmp_path):
    client, _ = make_client(tmp_path, lambda r: httpx.Response(401))
    async with client:
        with pytest.raises(ComicVineAuthError):
            await client.get_volume(1)


@pytest.mark.req("FRG-META-001")
async def test_cv_body_status_100_maps_to_auth_error(tmp_path):
    payload = {"error": "Invalid API Key", "status_code": 100, "results": {}}
    client, _ = make_client(tmp_path, lambda r: json_response(payload))
    async with client:
        with pytest.raises(ComicVineAuthError):
            await client.get_volume(1)


@pytest.mark.req("FRG-META-001")
async def test_429_maps_to_rate_limited(tmp_path):
    client, _ = make_client(
        tmp_path, lambda r: httpx.Response(429, headers={"retry-after": "1"})
    )
    async with client:
        with pytest.raises(ComicVineRateLimited) as exc:
            await client.get_volume(1)
    assert exc.value.retry_after == 1.0


@pytest.mark.req("FRG-META-001")
async def test_malformed_json_maps_to_malformed(tmp_path):
    client, _ = make_client(tmp_path, lambda r: httpx.Response(200, content=b"{not json"))
    async with client:
        with pytest.raises(ComicVineMalformedResponse):
            await client.get_volume(1)


@pytest.mark.req("FRG-META-001")
async def test_5xx_maps_to_unavailable(tmp_path):
    client, _ = make_client(tmp_path, lambda r: httpx.Response(503))
    async with client:
        with pytest.raises(ComicVineUnavailable):
            await client.get_volume(1)


@pytest.mark.req("FRG-META-001")
@pytest.mark.req("FRG-META-003")
async def test_ban_page_html_maps_to_rate_limited_not_data(tmp_path):
    client, _ = make_client(
        tmp_path, lambda r: httpx.Response(200, content=BAN_PAGE_HTML.encode())
    )
    async with client:
        with pytest.raises(ComicVineRateLimited):
            await client.get_volume(1)
    assert comicvine_degraded() is True  # ban treated as a rate-limit signal


# --- key redaction (FRG-META-002) -------------------------------------------


@pytest.mark.req("FRG-META-002")
async def test_full_flow_at_debug_never_emits_the_key(tmp_path):
    key = "CV-DEBUG-KEY-zzz999"
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    flog.register_secret(key)  # mirrors config-load registration
    setup_logging(config_dir, level="DEBUG")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/api/volumes"):
            return json_response(search_envelope([volume_payload()], total=1))
        if path.startswith("/api/volume/"):
            return json_response(volume_envelope())
        if path.startswith("/api/issues"):
            return json_response(issues_envelope([issue_payload()], total=1))
        return httpx.Response(404)

    settings = make_settings(
        config_dir, comicvine_api_key=key, comicvine_min_interval_seconds=0.25
    )
    resolver = StubResolver({CV_HOST: [PUBLIC_V4]})
    factory = HttpClientFactory(
        settings, resolver=resolver, transport=httpx.MockTransport(handler)
    )
    client = ComicVineClient(settings, factory, base=DEFAULT_BASE)
    async with client:
        await client.search_series("Saga")
        await client.get_volume(18166)
        await client.get_issues(18166)

    log_text = (config_dir / "logs" / "foragerr.log").read_text(encoding="utf-8")
    assert key not in log_text, "the API key leaked into the log file"
    assert "api_key=***REDACTED***" in log_text, (
        "expected the logged request URL's api_key to be redacted"
    )
