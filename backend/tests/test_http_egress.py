"""SSRF egress policy: hostile-fixture corpus, DNS handling, profiles,
policy-violation logging (FRG-SEC-001)."""

from __future__ import annotations

import logging

import httpx
import pytest

from foragerr.http import (
    EgressPolicyError,
    EgressValidator,
    HttpClientFactory,
)
from foragerr.logging import MASK
from http_support import (
    PUBLIC_V4,
    NoConnectTransport,
    RecordingTransport,
    StubResolver,
    make_settings,
)

# --------------------------------------------------------------------------
# Hostile-fixture corpus: refused by the external profile with NO connection
# attempted, asserted at the shared-client choke point (no bypass path).
# --------------------------------------------------------------------------

HOSTILE_FIXTURES = [
    # (url, expected reason fragment, expected offending address or None)
    ("http://127.0.0.1/admin", "loopback", "127.0.0.1"),
    ("http://[::1]/admin", "loopback", "::1"),
    ("http://2130706433/", "loopback", "127.0.0.1"),  # decimal-encoded IPv4
    ("http://0x7f000001/", "loopback", "127.0.0.1"),  # hex-encoded IPv4
    ("http://10.11.12.13/", "private (RFC 1918)", "10.11.12.13"),
    ("http://172.16.0.9/", "private (RFC 1918)", "172.16.0.9"),
    ("http://192.168.1.50/", "private (RFC 1918)", "192.168.1.50"),
    ("http://169.254.169.254/latest/meta-data/", "link-local", "169.254.169.254"),
    ("http://[fe80::1]/", "link-local", "fe80::1"),
    ("http://[fd00::5]/", "unique-local (ULA)", "fd00::5"),
    ("http://[::ffff:127.0.0.1]/", "loopback", "::ffff:127.0.0.1"),
    ("file:///etc/passwd", "forbidden scheme", None),
    ("ftp://mirror.example/", "forbidden scheme", None),
]


@pytest.mark.req("FRG-SEC-001")
@pytest.mark.parametrize("url,reason,offending", HOSTILE_FIXTURES)
async def test_hostile_fixture_refused_at_choke_point_without_connecting(
    tmp_path, url, reason, offending
):
    factory = HttpClientFactory(
        make_settings(tmp_path),
        resolver=StubResolver(),  # empty table: any DNS use would also refuse
        transport=NoConnectTransport(),  # any connection fails the test
    )
    async with factory.external() as client:
        with pytest.raises(EgressPolicyError) as excinfo:
            await client.get(url)
    err = excinfo.value
    assert reason in err.reason
    assert err.offending_address == offending
    if offending is not None:
        assert offending in str(err)  # names the offending resolved address


@pytest.mark.req("FRG-SEC-001")
async def test_ip_encoded_hosts_are_never_dns_resolved(tmp_path):
    """Decimal/hex IP encodings are interpreted as addresses, not names."""
    resolver = StubResolver()
    validator = EgressValidator(resolver=resolver)
    for url in ("http://2130706433/", "http://0x7f000001/", "http://127.0.0.1/"):
        with pytest.raises(EgressPolicyError):
            await validator.validate(httpx.URL(url))
    assert resolver.calls == []


@pytest.mark.req("FRG-SEC-001")
async def test_config_supplied_internal_image_url_refused(tmp_path):
    """A (ComicVine-style) response-supplied image URL pointing at an
    internal DNS name is refused before any connection."""
    resolver = StubResolver({"images.internal.lan": ["192.168.1.4"]})
    factory = HttpClientFactory(
        make_settings(tmp_path), resolver=resolver, transport=NoConnectTransport()
    )
    async with factory.external() as client:
        with pytest.raises(EgressPolicyError) as excinfo:
            await client.get("http://images.internal.lan/covers/1.jpg")
    assert excinfo.value.offending_address == "192.168.1.4"


@pytest.mark.req("FRG-SEC-001")
async def test_multi_record_dns_with_one_private_address_is_refused(tmp_path):
    """A name resolving to public+private A records is refused (rebinding-
    style mixed records), naming the private address."""
    resolver = StubResolver({"dual.example": [PUBLIC_V4, "10.0.0.5"]})
    validator = EgressValidator(resolver=resolver)
    with pytest.raises(EgressPolicyError) as excinfo:
        await validator.validate(httpx.URL("https://dual.example/feed"))
    assert excinfo.value.offending_address == "10.0.0.5"
    assert resolver.calls == ["dual.example"]


@pytest.mark.req("FRG-SEC-001")
async def test_public_resolving_host_passes_through_choke_point(tmp_path):
    resolver = StubResolver({"api.example": [PUBLIC_V4]})
    transport = RecordingTransport(lambda request: httpx.Response(200, content=b"{}"))
    factory = HttpClientFactory(
        make_settings(tmp_path), resolver=resolver, transport=transport
    )
    async with factory.external() as client:
        result = await client.get("https://api.example/v1/thing")
    assert result.status_code == 200
    assert [str(r.url) for r in transport.requests] == ["https://api.example/v1/thing"]


@pytest.mark.req("FRG-SEC-001")
async def test_unresolvable_host_is_refused_without_connecting(tmp_path):
    factory = HttpClientFactory(
        make_settings(tmp_path),
        resolver=StubResolver(),  # every lookup raises OSError
        transport=NoConnectTransport(),
    )
    async with factory.external() as client:
        with pytest.raises(EgressPolicyError) as excinfo:
            await client.get("https://nonexistent.example/")
    assert "DNS resolution failed" in excinfo.value.reason


# --------------------------------------------------------------------------
# Profiles: local-service allows exactly its configured base URL; external
# refuses the same address.
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-SEC-001")
async def test_local_service_allows_its_base_url_external_refuses_it(tmp_path):
    base = "http://192.168.1.10:8080"
    transport = RecordingTransport(lambda request: httpx.Response(200, content=b"ok"))
    factory = HttpClientFactory(
        make_settings(tmp_path), resolver=StubResolver(), transport=transport
    )

    async with factory.local_service(base) as sab:
        result = await sab.get(f"{base}/api?mode=queue")
    assert result.status_code == 200

    async with factory.external() as external:
        with pytest.raises(EgressPolicyError) as excinfo:
            await external.get(f"{base}/api?mode=queue")
    assert excinfo.value.reason == "private (RFC 1918)"
    # only the local-service request ever reached the transport
    assert len(transport.requests) == 1


@pytest.mark.req("FRG-SEC-001")
async def test_local_service_refuses_private_hosts_off_its_base_origin(tmp_path):
    factory = HttpClientFactory(
        make_settings(tmp_path),
        resolver=StubResolver(),
        transport=NoConnectTransport(),
    )
    async with factory.local_service("http://192.168.1.10:8080") as sab:
        for other in (
            "http://192.168.1.11:8080/",  # different host
            "http://192.168.1.10:9090/",  # different port
            "http://127.0.0.1/",  # loopback
        ):
            with pytest.raises(EgressPolicyError):
                await sab.get(other)


@pytest.mark.req("FRG-SEC-001")
async def test_local_service_rejects_malformed_base_url(tmp_path):
    factory = HttpClientFactory(make_settings(tmp_path), resolver=StubResolver())
    with pytest.raises(EgressPolicyError):
        factory.local_service("ftp://192.168.1.10/")
    with pytest.raises(EgressPolicyError):
        factory.local_service("not a url")


# --------------------------------------------------------------------------
# Policy violations are logged, naming the address, with the URL redacted.
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-SEC-001")
async def test_policy_violation_logged_with_offending_address_and_redacted_url(
    tmp_path, caplog
):
    validator = EgressValidator(resolver=StubResolver())
    secret = "supersecretkey12345"
    with caplog.at_level(logging.ERROR, logger="foragerr.http.egress"):
        with pytest.raises(EgressPolicyError) as excinfo:
            await validator.validate(
                httpx.URL(f"http://127.0.0.1/api?apikey={secret}&page=2")
            )
    record = next(
        rec for rec in caplog.records if "egress policy violation" in rec.getMessage()
    )
    message = record.getMessage()
    assert "127.0.0.1" in message  # names the offending address
    assert secret not in message and MASK in message  # api_key-shaped param masked
    assert "page=2" in message  # non-secret params stay readable
    # the exception text is redacted too (it may surface outside logging)
    assert secret not in str(excinfo.value) and MASK in str(excinfo.value)
