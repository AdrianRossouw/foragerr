"""Credential-lifecycle endpoints: web/OPDS password change, API-key rotate,
logout-all, credentials status (FRG-AUTH-004/005/006/007)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USER, TEST_API_KEY
from foragerr.app import create_app
from foragerr.auth import sessions as S
from foragerr.config import Settings

_ORIGIN = {"Origin": "http://testserver"}


def make_app(tmp_path: Path, name: str = "cfg"):
    path = tmp_path / name
    path.mkdir()
    return create_app(Settings(config_dir=path))


def _basic(user: str, password: str) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _login(client, password: str = TEST_ADMIN_PASSWORD, *, remember: bool = False):
    return client.post(
        "/api/v1/auth/login",
        json={
            "username": TEST_ADMIN_USER,
            "password": password,
            "remember": remember,
        },
    )


# -- web password change (FRG-AUTH-004) ---------------------------------------


@pytest.mark.req("FRG-AUTH-004")
def test_password_change_keeps_acting_kills_others(tmp_path):
    """The acting session survives a password change; every OTHER session
    (including a remember-me one) is revoked immediately."""
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        # Session A: a remember-me login on a separate (then-cleared) cookie jar.
        token_a = _login(client, remember=True).cookies[S.COOKIE_NAME]
        client.cookies.clear()
        # Session B: the acting session (cookie stays in the jar).
        _login(client)

        assert client.post(
            "/api/v1/auth/password",
            json={
                "current_password": TEST_ADMIN_PASSWORD,
                "new_password": "fresh-web-password",
            },
            headers=_ORIGIN,
        ).status_code == 204

        # Acting session B still works.
        assert client.get("/api/v1/auth/me").status_code == 200
        # The other remember-me session A is dead.
        client.cookies.clear()
        assert client.get(
            "/api/v1/auth/me", headers={"Cookie": f"{S.COOKIE_NAME}={token_a}"}
        ).status_code == 401


@pytest.mark.req("FRG-AUTH-005")
def test_web_password_change_does_not_change_opds_password(tmp_path):
    """Changing the web password leaves the OPDS password alone, even when both
    were seeded equal — they are independent credentials after seeding."""
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        _login(client)
        assert client.post(
            "/api/v1/auth/password",
            json={
                "current_password": TEST_ADMIN_PASSWORD,
                "new_password": "brand-new-web",
            },
            headers=_ORIGIN,
        ).status_code == 204
        # Drop the cookie so the OPDS Basic path is actually exercised.
        client.cookies.clear()
        # OPDS still accepts the ORIGINAL (seeded) password; not the new web one.
        assert client.get(
            "/opds", headers=_basic(TEST_ADMIN_USER, TEST_ADMIN_PASSWORD)
        ).status_code == 200
        assert client.get(
            "/opds", headers=_basic(TEST_ADMIN_USER, "brand-new-web")
        ).status_code == 401


@pytest.mark.req("FRG-AUTH-004")
def test_password_change_wrong_current_is_generic_403(tmp_path):
    """A wrong current password is refused with a generic 403 and changes
    nothing (the old password still logs in)."""
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        _login(client)
        resp = client.post(
            "/api/v1/auth/password",
            json={"current_password": "not-the-password", "new_password": "x"},
            headers=_ORIGIN,
        )
        assert resp.status_code == 403
        assert resp.json()["message"] == "re-authentication failed"
        # Unchanged: the real password still authenticates.
        client.cookies.clear()
        assert _login(client).status_code == 200


# -- OPDS password change (FRG-AUTH-005) --------------------------------------


@pytest.mark.req("FRG-AUTH-005")
def test_opds_password_change_updates_only_opds(tmp_path):
    """Changing the OPDS password (re-auth = admin password) swaps the Basic
    credential and never touches the web login."""
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        _login(client)
        assert client.post(
            "/api/v1/auth/opds-password",
            json={
                "current_password": TEST_ADMIN_PASSWORD,
                "new_password": "reader-only-pw",
            },
            headers=_ORIGIN,
        ).status_code == 204
        client.cookies.clear()
        # OPDS now takes the new reader password; the web login is unchanged.
        assert client.get(
            "/opds", headers=_basic(TEST_ADMIN_USER, "reader-only-pw")
        ).status_code == 200
        assert client.get(
            "/opds", headers=_basic(TEST_ADMIN_USER, TEST_ADMIN_PASSWORD)
        ).status_code == 401
        assert _login(client).status_code == 200  # web password intact


# -- logout-all (FRG-AUTH-004) ------------------------------------------------


@pytest.mark.req("FRG-AUTH-004")
def test_logout_all_kills_every_session_including_acting(tmp_path):
    """logout-all requires no password and revokes EVERY session, the acting one
    included — the shared-device recovery."""
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        token_a = _login(client).cookies[S.COOKIE_NAME]
        client.cookies.clear()
        token_b = _login(client).cookies[S.COOKIE_NAME]  # acting

        assert client.get("/api/v1/auth/me").status_code == 200
        resp = client.post("/api/v1/auth/logout-all", headers=_ORIGIN)
        assert resp.status_code == 204

        client.cookies.clear()
        for token in (token_a, token_b):
            assert client.get(
                "/api/v1/auth/me", headers={"Cookie": f"{S.COOKIE_NAME}={token}"}
            ).status_code == 401


# -- API-key rotation (FRG-AUTH-006/007) --------------------------------------


@pytest.mark.req("FRG-AUTH-007")
def test_api_key_rotate_invalidates_old_and_returns_new_once(tmp_path):
    """Rotation re-auths, returns the raw key exactly once, and the old key stops
    authenticating immediately while the new one works."""
    app = make_app(tmp_path)
    with TestClient(app) as client:  # authenticated by the seeded X-Api-Key
        resp = client.post(
            "/api/v1/auth/api-key/rotate",
            json={"current_password": TEST_ADMIN_PASSWORD},
        )
        assert resp.status_code == 200
        new_key = resp.json()["api_key"]
        assert new_key and new_key != TEST_API_KEY

        # Old key: 401 immediately. New key: works.
        assert client.get(
            "/api/v1/system/status", headers={"X-Api-Key": TEST_API_KEY}
        ).status_code == 401
        assert client.get(
            "/api/v1/system/status", headers={"X-Api-Key": new_key}
        ).status_code == 200
        # The raw key is not retrievable again (credentials returns only username).
        creds = client.get(
            "/api/v1/auth/credentials", headers={"X-Api-Key": new_key}
        ).json()
        assert creds == {"username": TEST_ADMIN_USER}
        assert "api_key" not in creds


@pytest.mark.req("FRG-AUTH-007")
def test_api_key_rotate_wrong_password_is_generic_403_key_unchanged(tmp_path):
    """A wrong current password is a generic 403 and does NOT rotate the key."""
    app = make_app(tmp_path)
    with TestClient(app) as client:  # seeded X-Api-Key attached by default
        resp = client.post(
            "/api/v1/auth/api-key/rotate",
            json={"current_password": "wrong-password"},
        )
        assert resp.status_code == 403
        assert resp.json()["message"] == "re-authentication failed"
        # The original key still authenticates — nothing rotated.
        assert client.get(
            "/api/v1/system/status", headers={"X-Api-Key": TEST_API_KEY}
        ).status_code == 200


@pytest.mark.req("FRG-AUTH-006")
def test_api_key_survives_web_password_change(tmp_path):
    """The API key is independent of the web password: changing the web password
    never invalidates the key."""
    app = make_app(tmp_path)
    with TestClient(app) as client:  # authenticated by the seeded X-Api-Key
        # Change over the API-key surface (CSRF-immune, so no Origin needed).
        assert client.post(
            "/api/v1/auth/password",
            json={
                "current_password": TEST_ADMIN_PASSWORD,
                "new_password": "new-web-pw",
            },
        ).status_code == 204
        # The default X-Api-Key still authenticates every subsequent request.
        assert client.get("/api/v1/system/status").status_code == 200


# -- new-password validation --------------------------------------------------


@pytest.mark.req("FRG-AUTH-004")
def test_empty_new_password_is_rejected(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/auth/password",
            json={"current_password": TEST_ADMIN_PASSWORD, "new_password": ""},
        )
        assert resp.status_code == 422


@pytest.mark.req("FRG-AUTH-004")
def test_oversized_current_password_is_generic_403_not_a_kdf_amplifier(tmp_path):
    """An oversized current_password is refused with the same generic 403 as a
    wrong one — capped BEFORE the scrypt call so it cannot inflate the re-auth
    KDF cost (gate hardening)."""
    app = make_app(tmp_path)
    with TestClient(app) as client:  # seeded X-Api-Key attached by default
        resp = client.post(
            "/api/v1/auth/password",
            json={"current_password": "x" * 5000, "new_password": "whatever-1"},
        )
        assert resp.status_code == 403
        assert resp.json()["message"] == "re-authentication failed"
        # The real password still works — nothing changed.
        assert client.post(
            "/api/v1/auth/password",
            json={"current_password": TEST_ADMIN_PASSWORD, "new_password": "new-pw-1"},
        ).status_code == 204


@pytest.mark.req("FRG-AUTH-007")
def test_rotation_drops_the_stale_bootstrap_key(tmp_path):
    """After rotation the never-retrieved bootstrap key is cleared: the one-shot
    handout would only ever return a dead key, so it is dropped rather than left
    as a dangling affordance."""
    app = make_app(tmp_path)
    with TestClient(app) as client:  # seeded X-Api-Key attached by default
        rotated = client.post(
            "/api/v1/auth/api-key/rotate",
            json={"current_password": TEST_ADMIN_PASSWORD},
        )
        new_key = rotated.json()["api_key"]
        # The bootstrap one-shot no longer hands out anything (404).
        assert client.post(
            "/api/v1/auth/bootstrap-key",
            headers={"X-Api-Key": new_key, **_ORIGIN},
        ).status_code == 404
        assert getattr(app.state, "bootstrap_api_key", None) is None

