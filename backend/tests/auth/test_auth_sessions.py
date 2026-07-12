"""Session management: opaque tokens, sliding tiers, fixation, logout, prune
(FRG-AUTH-004)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USER
from foragerr.app import create_app
from foragerr.auth import sessions as S
from foragerr.auth.models import PrincipalRow, SessionRow
from foragerr.auth.passwords import hash_password
from foragerr.config import Settings

_SETTINGS = SimpleNamespace(session_timeout_seconds=86_400, remember_timeout_seconds=7_776_000)


def make_app(tmp_path: Path, name: str = "cfg"):
    path = tmp_path / name
    path.mkdir()
    return create_app(Settings(config_dir=path)), path


async def _seed_principal(db) -> int:
    async with db.write_session() as session:
        row = PrincipalRow(
            username="admin",
            password_hash=hash_password("pw"),
            opds_password_hash=hash_password("pw"),
            api_key_sha256="0" * 64,
            created_at=dt.datetime(2026, 1, 1),
            updated_at=dt.datetime(2026, 1, 1),
        )
        session.add(row)
        await session.flush()
        return row.id


async def _session_count(db) -> int:
    async with db.read_session() as session:
        return (await session.execute(select(func.count()).select_from(SessionRow))).scalar_one()


# -- token storage + hashing --------------------------------------------------


@pytest.mark.req("FRG-AUTH-004")
async def test_only_token_hash_is_stored(db):
    pid = await _seed_principal(db)
    token = await S.create_session(db, pid, tier="session", settings=_SETTINGS)
    async with db.read_session() as session:
        row = (await session.execute(select(SessionRow))).scalar_one()
    # The raw token is never stored; only its SHA-256.
    assert row.token_sha256 == S.token_hash(token)
    assert row.token_sha256 != token
    assert len(token) >= 40  # 256-bit url-safe token


# -- sliding expiry per tier --------------------------------------------------


@pytest.mark.req("FRG-AUTH-004")
async def test_idle_standard_session_expires(db):
    pid = await _seed_principal(db)
    t0 = dt.datetime(2026, 1, 1, 12, 0, 0)
    token = await S.create_session(db, pid, tier="session", settings=_SETTINGS, now=t0)
    # 25 h later (> 24 h window), the standard session is expired.
    later = t0 + dt.timedelta(hours=25)
    assert await S.authenticate(db, token, settings=_SETTINGS, now=later) is None


@pytest.mark.req("FRG-AUTH-004")
async def test_remember_session_slides_forward(db):
    pid = await _seed_principal(db)
    t0 = dt.datetime(2026, 1, 1, 12, 0, 0)
    token = await S.create_session(db, pid, tier="remember", settings=_SETTINGS, now=t0)
    used = t0 + dt.timedelta(days=80)  # within the 90 d window
    authed = await S.authenticate(db, token, settings=_SETTINGS, now=used)
    assert authed is not None and authed.principal_id == pid
    async with db.read_session() as session:
        row = (await session.execute(select(SessionRow))).scalar_one()
    # Expiry slid forward to used + 90 d (not the original t0 + 90 d).
    assert row.expires_at == used + dt.timedelta(seconds=_SETTINGS.remember_timeout_seconds)


@pytest.mark.req("FRG-AUTH-004")
async def test_touch_is_throttled(db):
    pid = await _seed_principal(db)
    t0 = dt.datetime(2026, 1, 1, 12, 0, 0)
    token = await S.create_session(db, pid, tier="session", settings=_SETTINGS, now=t0)
    # A touch within the throttle window does not move last_seen.
    await S.authenticate(db, token, settings=_SETTINGS, now=t0 + dt.timedelta(seconds=30))
    async with db.read_session() as session:
        row = (await session.execute(select(SessionRow))).scalar_one()
    assert row.last_seen_at == t0  # < 60 s since create -> no write


# -- fixation + logout --------------------------------------------------------


@pytest.mark.req("FRG-AUTH-004")
def test_login_regenerates_token_old_cookie_dead(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        first = client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
        )
        old_token = first.cookies[S.COOKIE_NAME]
        # Log in again — a fresh token is issued (fixation defense).
        second = client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
        )
        new_token = second.cookies[S.COOKIE_NAME]
        assert new_token != old_token
        # The OLD token no longer authenticates.
        client.cookies.clear()
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Cookie": f"{S.COOKIE_NAME}={old_token}"},
        )
        assert resp.status_code == 401


@pytest.mark.req("FRG-AUTH-004")
def test_cookie_attributes(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
        )
    set_cookie = resp.headers["set-cookie"]
    lowered = set_cookie.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered
    assert "max-age=86400" in lowered  # standard tier default


@pytest.mark.req("FRG-AUTH-004")
def test_logout_revokes_server_side_and_replay_401(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        login = client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
        )
        token = login.cookies[S.COOKIE_NAME]
        assert client.get("/api/v1/auth/me").status_code == 200
        # logout is a cookie-authed POST, so it carries the same-origin Origin
        # header the browser sends (FRG-SEC-005 CSRF check).
        assert client.post(
            "/api/v1/auth/logout", headers={"Origin": "http://testserver"}
        ).status_code == 204
        # Replay the deleted cookie (back-button) -> 401.
        client.cookies.clear()
        assert client.get(
            "/api/v1/auth/me",
            headers={"Cookie": f"{S.COOKIE_NAME}={token}"},
        ).status_code == 401


# -- re-seed invalidation + prune ---------------------------------------------


@pytest.mark.req("FRG-AUTH-004")
def test_reseed_invalidates_all_sessions(tmp_path):
    app, cfg = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        token = client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
        ).cookies[S.COOKIE_NAME]

    import os

    os.environ["FORAGERR_ADMIN_PASSWORD"] = "brand-new-admin-password"
    try:
        app2 = create_app(Settings(config_dir=cfg))
        with TestClient(app2) as client2:
            client2.headers.pop("X-Api-Key", None)
            # The old session was deleted by the re-seed.
            assert client2.get(
                "/api/v1/auth/me",
                headers={"Cookie": f"{S.COOKIE_NAME}={token}"},
            ).status_code == 401
    finally:
        os.environ["FORAGERR_ADMIN_PASSWORD"] = TEST_ADMIN_PASSWORD


@pytest.mark.req("FRG-AUTH-004")
async def test_prune_removes_expired_rows(db):
    pid = await _seed_principal(db)
    t0 = dt.datetime(2026, 1, 1, 12, 0, 0)
    await S.create_session(db, pid, tier="session", settings=_SETTINGS, now=t0)
    live = await S.create_session(db, pid, tier="remember", settings=_SETTINGS, now=t0)
    assert await _session_count(db) == 2
    # Prune at t0 + 2 days: the 24 h standard row is expired, the 90 d row lives.
    pruned = await S.prune_expired(db, now=t0 + dt.timedelta(days=2))
    assert pruned == 1
    assert await _session_count(db) == 1
    assert await S.authenticate(db, live, settings=_SETTINGS, now=t0 + dt.timedelta(days=2)) is not None
