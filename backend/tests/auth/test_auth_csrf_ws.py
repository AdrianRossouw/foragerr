"""CSRF stance + WebSocket Origin validation (FRG-SEC-005)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USER, TEST_API_KEY
from foragerr.app import create_app
from foragerr.config import Settings


def make_app(tmp_path: Path, name: str = "cfg", **overrides):
    path = tmp_path / name
    path.mkdir()
    return create_app(Settings(config_dir=path, **overrides))


def _login(client) -> None:
    client.headers.pop("X-Api-Key", None)
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
    )
    assert resp.status_code == 200


# -- CSRF on the cookie surface -----------------------------------------------


@pytest.mark.req("FRG-SEC-005")
def test_cookie_post_foreign_origin_rejected_no_side_effect(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        _login(client)
        before = client.get("/api/v1/command", headers={"X-Api-Key": TEST_API_KEY}).json()
        resp = client.post(
            "/api/v1/command",
            json={"name": "noop"},
            headers={"Origin": "http://evil.example"},
        )
        assert resp.status_code == 403
        after = client.get("/api/v1/command", headers={"X-Api-Key": TEST_API_KEY}).json()
        # No command was created (no side effect).
        assert after["totalRecords"] == before["totalRecords"]


@pytest.mark.req("FRG-SEC-005")
def test_cookie_post_absent_origin_rejected(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        _login(client)
        # No Origin (and no Referer): an unsafe cookie-authed request is refused.
        resp = client.post("/api/v1/command", json={"name": "noop"})
        assert resp.status_code == 403


@pytest.mark.req("FRG-SEC-005")
def test_cookie_post_same_origin_allowed(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        _login(client)
        resp = client.post(
            "/api/v1/command",
            json={"name": "noop"},
            headers={"Origin": "http://testserver"},
        )
        assert resp.status_code == 201


@pytest.mark.req("FRG-SEC-005")
def test_cookie_post_referer_fallback_allowed(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        _login(client)
        # No Origin but a same-origin Referer is accepted.
        resp = client.post(
            "/api/v1/command",
            json={"name": "noop"},
            headers={"Referer": "http://testserver/series/1"},
        )
        assert resp.status_code == 201


@pytest.mark.req("FRG-SEC-005")
def test_api_key_surface_is_csrf_immune(tmp_path):
    """An X-Api-Key POST needs no Origin — the header cannot be attached
    cross-site, so the surface is CSRF-immune by construction."""
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        resp = client.post(
            "/api/v1/command",
            json={"name": "noop"},
            headers={"X-Api-Key": TEST_API_KEY},  # no Origin at all
        )
        assert resp.status_code == 201


@pytest.mark.req("FRG-SEC-005")
def test_configured_extra_origin_allows_cookie_post(tmp_path):
    app = make_app(tmp_path, auth_origin_allowlist="https://comics.example.org")
    with TestClient(app) as client:
        _login(client)
        resp = client.post(
            "/api/v1/command",
            json={"name": "noop"},
            headers={"Origin": "https://comics.example.org"},
        )
        assert resp.status_code == 201


# -- WebSocket Origin validation ----------------------------------------------


@pytest.mark.req("FRG-SEC-005")
def test_ws_bad_origin_refused_pre_upgrade(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/api/v1/ws",
                headers={"X-Api-Key": TEST_API_KEY, "Origin": "http://evil.example"},
            ):
                pass


@pytest.mark.req("FRG-SEC-005")
def test_ws_good_origin_with_credential_accepted(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v1/ws",
            headers={"X-Api-Key": TEST_API_KEY, "Origin": "http://testserver"},
        ) as ws:
            assert ws is not None  # handshake succeeded


@pytest.mark.req("FRG-SEC-005")
def test_ws_configured_extra_origin_accepted(tmp_path):
    app = make_app(tmp_path, auth_origin_allowlist="https://comics.example.org")
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v1/ws",
            headers={
                "X-Api-Key": TEST_API_KEY,
                "Origin": "https://comics.example.org",
            },
        ) as ws:
            assert ws is not None


@pytest.mark.req("FRG-AUTH-010")
def test_ws_without_credential_refused(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        # Drop the auto-auth key so the handshake carries no credential.
        client.headers.pop("X-Api-Key", None)
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/api/v1/ws", headers={"Origin": "http://testserver"}
            ):
                pass
