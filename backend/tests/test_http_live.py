"""Live fixture-server scenarios: timeouts, byte caps, redirect chains,
profile behavior over real sockets (FRG-NFR-006, FRG-SEC-001).

The servers bind 127.0.0.1. The production egress policy refuses loopback, so
tests reach them in one of two explicit, documented ways — neither weakens the
production policy:

- a ``local-service`` client whose configured base URL is the fixture server
  (exactly the operator-configured-LAN-integration path, e.g. SABnzbd); or
- the ``external`` profile with the validator's documented TEST-ONLY
  ``test_allow_addresses`` injection point listing 127.0.0.1.
"""

from __future__ import annotations

import time

import httpx
import pytest

from foragerr.http import (
    EgressPolicyError,
    HttpClientFactory,
    ResponseTooLargeError,
    TooManyRedirectsError,
)
from http_support import fixture_server, http_fixture_handler, make_settings

READ_TIMEOUT = 0.5


def _factory(tmp_path, **allow) -> HttpClientFactory:
    settings = make_settings(
        tmp_path,
        http_connect_timeout_seconds=2.0,
        http_read_timeout_seconds=READ_TIMEOUT,
        http_write_timeout_seconds=2.0,
        http_pool_timeout_seconds=2.0,
        http_max_response_bytes=4096,
    )
    return HttpClientFactory(settings, **allow)


# --------------------------------------------------------------------------
# FRG-NFR-006 — hung server aborts at the configured read timeout.
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-NFR-006")
async def test_hung_server_aborts_at_configured_read_timeout(tmp_path):
    log: list[str] = []
    async with fixture_server(http_fixture_handler(log)) as base:
        async with _factory(tmp_path).local_service(base) as client:
            started = time.monotonic()
            with pytest.raises(httpx.ReadTimeout):
                await client.get(f"{base}/hang")
            elapsed = time.monotonic() - started
            # aborted at the configured bound, not hanging indefinitely
            assert READ_TIMEOUT * 0.8 <= elapsed <= READ_TIMEOUT + 2.0
            # the worker/task is released, not wedged: the same client
            # immediately serves another request
            result = await client.get(f"{base}/ok")
            assert result.status_code == 200
    assert log == ["/hang", "/ok"]


# --------------------------------------------------------------------------
# FRG-NFR-006 — oversize and slow-drip bodies aborted at the byte cap.
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-NFR-006")
async def test_slow_drip_body_without_content_length_aborts_at_cap(tmp_path):
    """A server that omits Content-Length and drips an unbounded body is cut
    off at the cap; no unbounded buffer, no partial body to the caller."""
    log: list[str] = []
    async with fixture_server(http_fixture_handler(log)) as base:
        async with _factory(tmp_path).local_service(base) as client:
            with pytest.raises(ResponseTooLargeError):
                await client.get(f"{base}/drip")  # cap: 4096 bytes


@pytest.mark.req("FRG-NFR-006")
async def test_declared_oversize_content_length_refused_before_body_read(tmp_path):
    log: list[str] = []
    async with fixture_server(http_fixture_handler(log)) as base:
        async with _factory(tmp_path).local_service(base) as client:
            started = time.monotonic()
            with pytest.raises(ResponseTooLargeError):
                await client.get(f"{base}/big-declared")
            # refused from the headers alone — no attempt to stream ~1 GB
            assert time.monotonic() - started < 2.0


# --------------------------------------------------------------------------
# FRG-NFR-006 — redirect chains over real sockets.
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-NFR-006")
async def test_live_redirect_chains_bounded_at_five_hops(tmp_path):
    log: list[str] = []
    async with fixture_server(http_fixture_handler(log)) as base:
        async with _factory(tmp_path).local_service(base) as client:
            # 4 redirect hops: succeeds
            result = await client.get(f"{base}/r/4")
            assert result.status_code == 200
            assert result.content == b"ok"
            assert log == ["/r/4", "/r/3", "/r/2", "/r/1", "/r/0"]

            # 6 redirect responses: stops after the 5th followed hop
            log.clear()
            with pytest.raises(TooManyRedirectsError):
                await client.get(f"{base}/r/6")
            assert log == ["/r/6", "/r/5", "/r/4", "/r/3", "/r/2", "/r/1"]


@pytest.mark.req("FRG-NFR-006")
@pytest.mark.req("FRG-SEC-001")
async def test_external_profile_via_documented_test_allowlist(tmp_path):
    """The validator's test-only allowlist admits the fixture address for the
    external profile — and without it the same URL is refused, proving the
    production default stays closed."""
    log: list[str] = []
    async with fixture_server(http_fixture_handler(log)) as base:
        allowed = _factory(tmp_path, test_allow_addresses={"127.0.0.1"})
        async with allowed.external() as client:
            result = await client.get(f"{base}/r/2")
            assert result.status_code == 200

        strict = _factory(tmp_path)
        requests_before = list(log)
        async with strict.external() as client:
            with pytest.raises(EgressPolicyError) as excinfo:
                await client.get(f"{base}/ok")
        assert excinfo.value.offending_address == "127.0.0.1"
        assert log == requests_before  # refused with no connection made


# --------------------------------------------------------------------------
# FRG-SEC-001 — local-service allows its configured base; external refuses
# the very same private address (live).
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-SEC-001")
async def test_local_service_reaches_its_base_where_external_is_refused(tmp_path):
    log: list[str] = []
    async with fixture_server(http_fixture_handler(log)) as base:
        factory = _factory(tmp_path)
        async with factory.local_service(base) as sab:
            result = await sab.get(f"{base}/ok")
            assert result.status_code == 200
        async with factory.external() as external:
            with pytest.raises(EgressPolicyError):
                await external.get(f"{base}/ok")
    assert log == ["/ok"]  # exactly one connection: the local-service one


@pytest.mark.req("FRG-SEC-001")
async def test_local_service_redirect_leaving_base_origin_is_revalidated(tmp_path):
    """Even a trusted local service cannot bounce the client to another
    private host: hops off the base origin get the full external policy."""

    async def redirect_to_other_private(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 302 Found\r\nLocation: http://192.168.0.99/steal\r\n"
            b"Content-Length: 0\r\nConnection: close\r\n\r\n"
        )
        await writer.drain()

    async with fixture_server(redirect_to_other_private) as base:
        async with _factory(tmp_path).local_service(base) as client:
            with pytest.raises(EgressPolicyError) as excinfo:
                await client.get(f"{base}/api")
    assert excinfo.value.offending_address == "192.168.0.99"
