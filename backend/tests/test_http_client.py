"""Outbound client factory behavior: construction invariants, manual redirect
walk with per-hop validation, credential scoping (FRG-NFR-006, FRG-SEC-001)."""

from __future__ import annotations

import inspect
import ssl

import httpx
import pytest

from foragerr.http import (
    MAX_REDIRECTS,
    EgressPolicyError,
    HttpClientFactory,
    OutboundClient,
    TooManyRedirectsError,
)
from http_support import (
    PUBLIC_V4,
    RecordingTransport,
    StubResolver,
    make_settings,
)

# --------------------------------------------------------------------------
# FRG-NFR-006 — client construction: explicit timeouts, TLS verify on,
# no opt-out parameter, redirects disabled.
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-NFR-006")
async def test_factory_clients_carry_explicit_timeouts_and_no_auto_redirects(
    tmp_path,
):
    settings = make_settings(
        tmp_path,
        http_connect_timeout_seconds=3.5,
        http_read_timeout_seconds=7.0,
        http_write_timeout_seconds=8.0,
        http_pool_timeout_seconds=9.0,
    )
    factory = HttpClientFactory(settings)
    for client in (factory.external(), factory.local_service("http://sab.lan:8080")):
        async with client:
            timeout = client._client.timeout
            assert timeout.connect == 3.5
            assert timeout.read == 7.0
            assert timeout.write == 8.0
            assert timeout.pool == 9.0
            assert None not in (
                timeout.connect,
                timeout.read,
                timeout.write,
                timeout.pool,
            ), "no timeout may default to unlimited"
            assert client._client.follow_redirects is False


@pytest.mark.req("FRG-NFR-006")
async def test_factory_clients_verify_tls(tmp_path):
    factory = HttpClientFactory(make_settings(tmp_path))
    async with factory.external() as client:
        context = client._client._transport._pool._ssl_context
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True


@pytest.mark.req("FRG-NFR-006")
def test_factory_api_exposes_no_tls_verification_opt_out():
    """The factory API deliberately has no per-call/per-host verify opt-out."""
    forbidden = {"verify", "ssl", "cert", "insecure", "verify_ssl", "tls_verify"}
    for func in (
        HttpClientFactory.__init__,
        HttpClientFactory.external,
        HttpClientFactory.local_service,
        OutboundClient.request,
        OutboundClient.get,
        OutboundClient.post,
    ):
        params = set(inspect.signature(func).parameters)
        assert not params & forbidden, f"{func.__qualname__} exposes {params & forbidden}"


# --------------------------------------------------------------------------
# FRG-NFR-006 + FRG-SEC-001 — manual redirect walk, bounded, per-hop validated.
# --------------------------------------------------------------------------


def _chain_handler(final_body: bytes = b"done"):
    """MockTransport handler serving /r/<n> redirect chains on any host."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/r/"):
            hops_left = int(path[3:])
            if hops_left > 0:
                return httpx.Response(
                    302, headers={"location": f"/r/{hops_left - 1}"}
                )
            return httpx.Response(200, content=final_body)
        return httpx.Response(200, content=b"root")

    return handler


@pytest.mark.req("FRG-NFR-006")
async def test_six_redirects_raise_bounded_error_after_five_hops(tmp_path):
    resolver = StubResolver({"chain.example": [PUBLIC_V4]})
    transport = RecordingTransport(_chain_handler())
    factory = HttpClientFactory(
        make_settings(tmp_path), resolver=resolver, transport=transport
    )
    async with factory.external() as client:
        with pytest.raises(TooManyRedirectsError):
            await client.get("https://chain.example/r/6")
    # initial request + exactly MAX_REDIRECTS followed hops, then stop
    assert len(transport.requests) == MAX_REDIRECTS + 1


@pytest.mark.req("FRG-NFR-006")
@pytest.mark.req("FRG-SEC-001")
async def test_four_hop_chain_succeeds_with_every_hop_egress_validated(tmp_path):
    resolver = StubResolver({"chain.example": [PUBLIC_V4]})
    transport = RecordingTransport(_chain_handler(b"payload"))
    factory = HttpClientFactory(
        make_settings(tmp_path), resolver=resolver, transport=transport
    )
    async with factory.external() as client:
        result = await client.get("https://chain.example/r/4")
    assert result.status_code == 200
    assert result.content == b"payload"
    assert result.url == "https://chain.example/r/0"
    assert [r.url.path for r in transport.requests] == [
        "/r/4",
        "/r/3",
        "/r/2",
        "/r/1",
        "/r/0",
    ]
    # the egress layer observed (resolved) every hop, including the initial one
    assert resolver.calls == ["chain.example"] * 5


@pytest.mark.req("FRG-SEC-001")
async def test_redirect_hop_to_private_target_is_dropped(tmp_path):
    """A public host redirecting to a private target (directly or via a DNS
    name resolving there) is re-validated and refused — no connection."""
    resolver = StubResolver(
        {"good.example": [PUBLIC_V4], "internal.example": ["10.9.8.7"]}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "good.example":
            target = request.url.params.get("to", "http://192.168.0.1/admin")
            return httpx.Response(302, headers={"location": target})
        raise AssertionError(f"connected to redirect target {request.url}")

    transport = RecordingTransport(handler)
    factory = HttpClientFactory(
        make_settings(tmp_path), resolver=resolver, transport=transport
    )
    async with factory.external() as client:
        for target in ("http://192.168.0.1/admin", "http://internal.example/x"):
            with pytest.raises(EgressPolicyError):
                await client.get("https://good.example/download", params={"to": target})
    # only the public origin was ever contacted
    assert {r.url.host for r in transport.requests} == {"good.example"}


@pytest.mark.req("FRG-SEC-001")
async def test_credentials_not_forwarded_to_cross_host_redirect(tmp_path):
    resolver = StubResolver({"a.example": [PUBLIC_V4], "b.example": [PUBLIC_V4]})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "a.example" and request.url.path == "/start":
            return httpx.Response(302, headers={"location": "https://b.example/land"})
        if request.url.host == "a.example" and request.url.path == "/other":
            return httpx.Response(302, headers={"location": "/same-host-land"})
        return httpx.Response(200, content=b"ok")

    transport = RecordingTransport(handler)
    factory = HttpClientFactory(
        make_settings(tmp_path), resolver=resolver, transport=transport
    )
    credentials = {
        "Authorization": "Bearer token-abc",
        "Cookie": "session=xyz",
        "X-Api-Key": "key-123",
    }

    async with factory.external() as client:
        await client.get("https://a.example/start", headers=credentials)
        first, second = transport.requests
        # originating host received the credentials...
        assert first.headers["authorization"] == "Bearer token-abc"
        assert first.headers["cookie"] == "session=xyz"
        assert first.headers["x-api-key"] == "key-123"
        # ...the cross-host redirect target received NONE of them
        assert second.url.host == "b.example"
        for header in ("authorization", "cookie", "x-api-key"):
            assert header not in second.headers

        # same-host redirects keep the integration's credentials
        transport.requests.clear()
        await client.get("https://a.example/other", headers=credentials)
        same_host_hop = transport.requests[1]
        assert same_host_hop.url.path == "/same-host-land"
        assert same_host_hop.headers["authorization"] == "Bearer token-abc"


@pytest.mark.req("FRG-NFR-006")
async def test_per_request_cap_may_lower_but_never_raise_configured_cap(tmp_path):
    from foragerr.http import ResponseTooLargeError

    body = b"z" * 2048
    transport = RecordingTransport(lambda request: httpx.Response(200, content=body))
    resolver = StubResolver({"api.example": [PUBLIC_V4]})
    factory = HttpClientFactory(
        make_settings(tmp_path, http_max_response_bytes=1024 * 1024),
        resolver=resolver,
        transport=transport,
    )
    async with factory.external() as client:
        # within the configured cap: succeeds
        result = await client.get("https://api.example/big")
        assert result.content == body
        # a caller may lower the cap for one request...
        with pytest.raises(ResponseTooLargeError):
            await client.get("https://api.example/big", max_bytes=1024)

    # ...but can never raise it past the configured ceiling
    tight = HttpClientFactory(
        make_settings(tmp_path, http_max_response_bytes=1024),
        resolver=resolver,
        transport=transport,
    )
    async with tight.external() as client:
        with pytest.raises(ResponseTooLargeError):
            await client.get("https://api.example/big", max_bytes=999_999)
