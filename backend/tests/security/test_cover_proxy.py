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


def _install(monkeypatch, result: _FakeResult) -> _FakeClient:
    client = _FakeClient(result)

    class _FakeFactory:
        def __init__(self, settings) -> None:
            pass

        def external(self) -> _FakeClient:
            return client

    monkeypatch.setattr(cover_proxy, "HttpClientFactory", _FakeFactory)
    return client


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
