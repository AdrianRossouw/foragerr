"""Same-origin candidate-cover proxy (FRG-META-021): allowlist, content
verification, auth, and bounds — the abuse scenarios for the one endpoint
that fetches a client-supplied URL."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from foragerr.api import cover_proxy
from foragerr.app import create_app
from foragerr.config import Settings

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


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

    async def get(self, url, **kw):
        self.calls.append(str(url))
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
    URL 302ing to a public non-CV host is refused, not followed."""
    class _Url:
        def __init__(self, scheme, host):
            self.scheme = scheme
            self.host = host

    cover_proxy._hop_check(_Url("https", "comicvine.gamespot.com"))  # ok
    for scheme, host in (
        ("https", "evil.example.com"),
        ("https", "evilcomicvine.com"),
        ("http", "comicvine.gamespot.com"),
    ):
        with pytest.raises(ValueError):
            cover_proxy._hop_check(_Url(scheme, host))


# --- shared-endpoint rule (s3.amazonaws.com + required /comicgeeks/ prefix) ---

S3_COVER = "https://s3.amazonaws.com/comicgeeks/comics/covers/large-90210.jpg"


class _HopUrl:
    """Stand-in for the httpx.URL the factory hands the per-hop validator:
    ``raw_path`` is the path+query as sent, still percent-encoded."""

    def __init__(self, scheme: str, host: str, raw_path: bytes = b"/") -> None:
        self.scheme = scheme
        self.host = host
        self.raw_path = raw_path


class _HopRefusingClient:
    """Answers only after the endpoint's hop_check has passed on a redirect
    target — so a refused hop aborts before any body is produced."""

    def __init__(self, hop_url: _HopUrl) -> None:
        self._hop_url = hop_url
        self.calls: list[str] = []

    async def get(self, url, **kw):
        self.calls.append(str(url))
        kw["hop_check"](self._hop_url)
        return _FakeResult(PNG)

    async def aclose(self) -> None:
        return None


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
    cover_proxy._hop_check(_HopUrl("https", "s3.amazonaws.com", b"/comicgeeks/x.jpg"))
    for hop in (
        _HopUrl("https", "s3.amazonaws.com", b"/other-bucket/x.jpg"),
        _HopUrl("https", "s3.amazonaws.com", b"/comicgeeks-evil/x.jpg"),
        _HopUrl("https", "s3.amazonaws.com", b"/comicgeeks/%2e%2e/other/x.jpg"),
        _HopUrl("https", "comicgeeks.s3.amazonaws.com", b"/comicgeeks/x.jpg"),
        _HopUrl("https", "s3.amazonaws.com", b"/"),
    ):
        with pytest.raises(ValueError):
            cover_proxy._hop_check(hop)


@pytest.mark.req("FRG-META-021")
def test_redirect_hop_off_the_rules_serves_zero_body_bytes(app, monkeypatch):
    fake = _install_client(
        monkeypatch,
        _HopRefusingClient(
            _HopUrl("https", "s3.amazonaws.com", b"/other-bucket/x.jpg")
        ),
    )
    with TestClient(app) as client:
        r = client.get(
            "/api/v1/metadata/cover",
            params={"src": "https://comicvine.gamespot.com/a/cover.png"},
        )
    assert r.status_code == 502
    assert PNG not in r.content
    assert fake.calls  # the fetch started, the hop aborted it mid-flight
