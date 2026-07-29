"""Same-origin candidate-cover proxy (FRG-META-021): allowlist, content
verification, auth, and bounds — the abuse scenarios for the one endpoint
that fetches a client-supplied URL."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from foragerr.api import cover_proxy
from foragerr.app import create_app
from foragerr.config import Settings
from foragerr.http import HttpClientFactory

from http_support import PUBLIC_V4, StubResolver, make_settings

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32

#: Every host a redirect-chain test can hop to, all mapped to a policy-clean
#: public address so the egress SSRF check passes and the cover allowlist (the
#: hop_check) is the control actually under test.
_REDIRECT_HOSTS = (
    "comicvine.gamespot.com",
    "evil.example.com",
    "s3.amazonaws.com",
    "comicgeeks.s3.amazonaws.com",
)

#: The allowlisted URL a redirect chain starts from.
CV_START = "https://comicvine.gamespot.com/a/cover.png"


class _FakeResult:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code
        self.headers = {}
        self.url = "https://comicvine.gamespot.com/x.png"


class _FakeClient:
    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.calls: list[str] = []
        self.raw_urls: list = []
        self.kwargs: list[dict] = []

    async def get(self, url, **kw):
        self.calls.append(str(url))
        self.raw_urls.append(url)
        self.kwargs.append(kw)
        return self._result

    async def aclose(self) -> None:
        return None


@pytest.fixture
def app(tmp_path):
    path = tmp_path / "cfg"
    path.mkdir()
    cover_proxy.reset_cache()
    return create_app(Settings(config_dir=path))


def _install_client(monkeypatch, client):
    class _FakeFactory:
        def __init__(self, settings) -> None:
            pass

        def external(self):
            return client

    monkeypatch.setattr(cover_proxy, "HttpClientFactory", _FakeFactory)
    return client


def _install(monkeypatch, result: _FakeResult) -> _FakeClient:
    return _install_client(monkeypatch, _FakeClient(result))


def _install_redirect_factory(monkeypatch, tmp_path, location: str) -> list[httpx.Request]:
    """Patch the endpoint's factory with a REAL :class:`HttpClientFactory` over
    an ``httpx.MockTransport`` that 302s the CV start URL to ``location`` (and
    answers a real PNG for any non-CV host). The factory hands the endpoint's
    ``_hop_check`` the actual ``httpx.URL`` it walks — raw_path and all — so the
    load-bearing wire-form decision is exercised for real. Returns the list the
    transport records every reached request into."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "comicvine.gamespot.com":
            return httpx.Response(302, headers={"location": location})
        return httpx.Response(200, content=PNG)

    resolver = StubResolver({host: [PUBLIC_V4] for host in _REDIRECT_HOSTS})
    transport = httpx.MockTransport(handler)

    real_factory = HttpClientFactory(
        make_settings(tmp_path), resolver=resolver, transport=transport
    )

    class _RealFactory:
        def __init__(self, settings) -> None:
            pass

        def external(self):
            return real_factory.external()

    monkeypatch.setattr(cover_proxy, "HttpClientFactory", _RealFactory)
    return seen


@pytest.mark.req("FRG-META-021")
def test_allowlisted_cover_proxies_with_sniffed_type(app, monkeypatch):
    _install(monkeypatch, _FakeResult(PNG))
    with TestClient(app) as client:
        r = client.get(
            "/api/v1/metadata/cover",
            params={"src": "https://comicvine.gamespot.com/a/uploads/scale_small/x.png"},
        )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == PNG


@pytest.mark.req("FRG-META-021")
def test_off_allowlist_and_lookalike_hosts_refused_before_fetch(app, monkeypatch):
    fake = _install(monkeypatch, _FakeResult(PNG))
    with TestClient(app) as client:
        for src in (
            "https://evil.example.com/x.png",
            "https://evilcomicvine.gamespot.com.evil.example/x.png",
            "https://notgamespot.com/comicvine.gamespot.com/x.png",
            "http://comicvine.gamespot.com/x.png",  # non-HTTPS
        ):
            r = client.get("/api/v1/metadata/cover", params={"src": src})
            assert r.status_code == 400, src
    assert fake.calls == []  # never fetched


@pytest.mark.req("FRG-META-021")
def test_non_image_content_never_served(app, monkeypatch):
    _install(monkeypatch, _FakeResult(b"<html>surprise login page</html>"))
    with TestClient(app) as client:
        r = client.get(
            "/api/v1/metadata/cover",
            params={"src": "https://comicvine.gamespot.com/x.png"},
        )
    assert r.status_code == 502
    assert b"surprise" not in r.content


@pytest.mark.req("FRG-META-021")
def test_unauthenticated_denied_before_fetch(app, monkeypatch):
    fake = _install(monkeypatch, _FakeResult(PNG))
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        r = client.get(
            "/api/v1/metadata/cover",
            params={"src": "https://comicvine.gamespot.com/x.png"},
        )
    assert r.status_code == 401
    assert fake.calls == []


@pytest.mark.req("FRG-META-021")
def test_cache_serves_repeats_without_refetch(app, monkeypatch):
    fake = _install(monkeypatch, _FakeResult(JPEG))
    with TestClient(app) as client:
        for _ in range(3):
            r = client.get(
                "/api/v1/metadata/cover",
                params={"src": "https://comicvine.gamespot.com/a/cover.jpg"},
            )
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("image/jpeg")
    assert len(fake.calls) == 1  # LRU-cached after first fetch


@pytest.mark.req("FRG-META-021")
def test_hop_check_pins_redirect_targets_to_allowlist():
    """The per-hop validator refuses any hop off the cover allowlist — a CV
    URL 302ing to a public non-CV host is refused, not followed. Driven over
    REAL ``httpx.URL`` objects (which carry the ``raw_path`` the check reads),
    the exact object the factory hands the validator mid-walk."""
    cover_proxy._hop_check(httpx.URL("https://comicvine.gamespot.com/a/x.png"))  # ok
    for url in (
        "https://evil.example.com/x.png",
        "https://evilcomicvine.com/x.png",
        "http://comicvine.gamespot.com/x.png",  # scheme downgrade
        "https://comicvine.gamespot.com:8443/x.png",  # non-default port
        "https://u:p@comicvine.gamespot.com/x.png",  # userinfo
    ):
        with pytest.raises(ValueError):
            cover_proxy._hop_check(httpx.URL(url))


# --- shared-endpoint rule (s3.amazonaws.com + required /comicgeeks/ prefix) ---

S3_COVER = "https://s3.amazonaws.com/comicgeeks/comics/covers/large-90210.jpg"


@pytest.mark.req("FRG-META-021")
def test_shared_host_cover_under_required_prefix_proxies(app, monkeypatch):
    _install(monkeypatch, _FakeResult(JPEG))
    with TestClient(app) as client:
        r = client.get(
            "/api/v1/metadata/cover", params={"src": S3_COVER + "?1753900000"}
        )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")
    assert r.content == JPEG


@pytest.mark.req("FRG-META-021")
def test_shared_host_other_bucket_and_prefix_lookalike_refused_before_fetch(
    app, monkeypatch
):
    fake = _install(monkeypatch, _FakeResult(PNG))
    with TestClient(app) as client:
        for src in (
            "https://s3.amazonaws.com/other-bucket/x.jpg",
            "https://s3.amazonaws.com/comicgeeks-evil/x.jpg",
            "https://s3.amazonaws.com/comicgeeks",  # prefix needs the boundary
            "https://s3.amazonaws.com/x.jpg",
        ):
            r = client.get("/api/v1/metadata/cover", params={"src": src})
            assert r.status_code == 400, src
    assert fake.calls == []  # never fetched


@pytest.mark.req("FRG-META-021")
def test_shared_host_traversal_refused_at_every_encoding_depth(app, monkeypatch):
    fake = _install(monkeypatch, _FakeResult(PNG))
    with TestClient(app) as client:
        for src in (
            "https://s3.amazonaws.com/comicgeeks/../other-bucket/x.jpg",
            "https://s3.amazonaws.com/comicgeeks/%2e%2e/other-bucket/x.jpg",
            # Double-encoded: a second decode must never turn this into a pass.
            "https://s3.amazonaws.com/comicgeeks/%252e%252e/other-bucket/x.jpg",
            "https://s3.amazonaws.com/comicgeeks/%5c..%5cother-bucket/x.jpg",
            "https://comicvine.gamespot.com/a/../../etc/passwd",
        ):
            r = client.get("/api/v1/metadata/cover", params={"src": src})
            assert r.status_code == 400, src
    assert fake.calls == []


@pytest.mark.req("FRG-META-021")
def test_virtual_hosted_bucket_subdomains_of_shared_host_refused(app, monkeypatch):
    fake = _install(monkeypatch, _FakeResult(PNG))
    with TestClient(app) as client:
        for src in (
            "https://comicgeeks.s3.amazonaws.com/comics/covers/large-90210.jpg",
            "https://comicgeeks.s3.amazonaws.com/comicgeeks/x.jpg",
            "https://other-bucket.s3.amazonaws.com/x.jpg",
        ):
            r = client.get("/api/v1/metadata/cover", params={"src": src})
            assert r.status_code == 400, src
    assert fake.calls == []


@pytest.mark.req("FRG-META-021")
def test_evaluator_is_shared_and_agrees_with_the_endpoint():
    """The exported evaluator is the single source of truth both gates use."""
    assert cover_proxy.cover_url_allowed(S3_COVER)
    assert cover_proxy.cover_url_allowed(
        "https://comicvine.gamespot.com/a/uploads/scale_small/x.png"
    )
    for src in (
        "http://s3.amazonaws.com/comicgeeks/x.jpg",  # non-HTTPS
        "https://s3.amazonaws.com/other-bucket/x.jpg",
        "https://comicgeeks.s3.amazonaws.com/x.jpg",
        "https://s3.amazonaws.com/comicgeeks/%252e%252e/other/x.jpg",
        "/assets/images/no-cover-lg.jpg",  # relative placeholder
    ):
        assert not cover_proxy.cover_url_allowed(src), src


@pytest.mark.req("FRG-META-021")
def test_hop_check_reevaluates_the_shared_host_rules():
    """The shared-endpoint prefix/exact-host rules are re-run per hop over real
    ``httpx.URL`` objects — a hop whose wire path leaves ``/comicgeeks/`` (or a
    virtual-hosted bucket subdomain) is refused mid-flight."""
    cover_proxy._hop_check(httpx.URL("https://s3.amazonaws.com/comicgeeks/x.jpg"))
    for url in (
        "https://s3.amazonaws.com/other-bucket/x.jpg",
        "https://s3.amazonaws.com/comicgeeks-evil/x.jpg",
        "https://s3.amazonaws.com/comicgeeks/%2e%2e/other/x.jpg",
        "https://comicgeeks.s3.amazonaws.com/comicgeeks/x.jpg",
        "https://s3.amazonaws.com/",
    ):
        with pytest.raises(ValueError):
            cover_proxy._hop_check(httpx.URL(url))


# A redirect target the walk must REFUSE, and the one it may FOLLOW — driven
# for real through HttpClientFactory + httpx.MockTransport so the endpoint's
# hop_check runs against the object the factory truly passes it.
_REFUSED_REDIRECTS = [
    "https://evil.example.com/x.png",  # off-host
    "//evil.example.com/x.png",  # scheme-relative off-host
    "http://comicvine.gamespot.com/x.png",  # scheme downgrade
    "https://s3.amazonaws.com/other-bucket/x.jpg",  # shared host, wrong bucket
    "https://comicgeeks.s3.amazonaws.com/comicgeeks/x.jpg",  # virtual-hosted bucket
]


@pytest.mark.req("FRG-META-021")
@pytest.mark.parametrize("location", _REFUSED_REDIRECTS)
def test_redirect_hop_off_the_rules_serves_zero_body_bytes(
    app, monkeypatch, tmp_path, location
):
    seen = _install_redirect_factory(monkeypatch, tmp_path, location)
    with TestClient(app) as client:
        r = client.get("/api/v1/metadata/cover", params={"src": CV_START})
    assert r.status_code == 502, location
    assert PNG not in r.content
    # The first hop reached the transport (the 302); the refused hop aborted
    # the walk before its own request was ever sent.
    assert [req.url.host for req in seen] == ["comicvine.gamespot.com"], location


@pytest.mark.req("FRG-META-021")
def test_redirect_hop_within_the_required_prefix_is_followed_and_served(
    app, monkeypatch, tmp_path
):
    """A 302 to another ``/comicgeeks/`` path is on-allowlist at every hop, so
    it is followed and the fetched image is served."""
    seen = _install_redirect_factory(
        monkeypatch, tmp_path, "https://s3.amazonaws.com/comicgeeks/covers/other.jpg"
    )
    with TestClient(app) as client:
        r = client.get("/api/v1/metadata/cover", params={"src": CV_START})
    assert r.status_code == 200
    assert r.content == PNG
    assert [req.url.host for req in seen] == [
        "comicvine.gamespot.com",
        "s3.amazonaws.com",
    ]


# --- malformed src, cache-key collapse, wire-form fetch, byte cap ------------


@pytest.mark.req("FRG-META-021")
def test_malformed_src_is_400_field_src_not_500_and_never_fetches(app, monkeypatch):
    """A src whose authority ``urlsplit`` cannot parse fails closed to a 400
    (field ``src``) through the TOTAL evaluator — never an unguarded 500, and
    the fetch logic is never reached."""
    fake = _install(monkeypatch, _FakeResult(PNG))
    with TestClient(app) as client:
        for src in (
            "https://[::1/comicgeeks/x.jpg",  # unbalanced bracket
            "https://evil[.]com]/comicgeeks/x.jpg",  # stray bracket
            "https://[:::]/comicgeeks/x.jpg",  # bad IPv6
        ):
            r = client.get("/api/v1/metadata/cover", params={"src": src})
            assert r.status_code == 400, src
            assert r.json()["errors"][0]["field"] == "src", src
    assert fake.calls == []  # never fetched


@pytest.mark.req("FRG-META-021")
def test_query_variants_of_one_image_share_one_cache_entry(app, monkeypatch):
    """Two spellings of one cover differing only by the volatile cache-buster
    query collapse to one canonical cache key — the second request is served
    from cache and never re-hits the transport."""
    fake = _install(monkeypatch, _FakeResult(JPEG))
    base = "https://s3.amazonaws.com/comicgeeks/comics/covers/large-1.jpg"
    with TestClient(app) as client:
        first = client.get("/api/v1/metadata/cover", params={"src": base + "?cb=111"})
        second = client.get("/api/v1/metadata/cover", params={"src": base + "?cb=222"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(fake.calls) == 1  # one upstream fetch for both spellings


@pytest.mark.req("FRG-META-021")
def test_fetched_url_is_the_callers_wire_form(app, monkeypatch):
    """The FETCHED url is the caller's wire form byte-for-byte — percent-escapes
    (``%2f``, ``%63``) survive to the transport, never a decoded rebuild that
    would change what the remote receives."""
    fake = _install(monkeypatch, _FakeResult(PNG))
    src = "https://s3.amazonaws.com/comicgeeks/a%2fb%63.jpg"
    with TestClient(app) as client:
        r = client.get("/api/v1/metadata/cover", params={"src": src})
    assert r.status_code == 200
    assert fake.calls == [src]
    assert "%2f" in fake.calls[0] and "%63" in fake.calls[0]


@pytest.mark.req("FRG-META-021")
def test_byte_cap_is_passed_to_the_factory_get(app, monkeypatch):
    """The streaming byte cap is handed to the outbound factory on every fetch,
    so no cover response can exceed it."""
    fake = _install(monkeypatch, _FakeResult(PNG))
    with TestClient(app) as client:
        r = client.get(
            "/api/v1/metadata/cover",
            params={"src": "https://comicvine.gamespot.com/a/cover.png"},
        )
    assert r.status_code == 200
    assert fake.kwargs[0]["max_bytes"] == cover_proxy.MAX_COVER_BYTES
