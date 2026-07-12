"""Env re-seed fingerprints (FRG-AUTH-002, FRG-AUTH-005).

The m8-keys-opds semantics: re-seed is measured against the last-seeded env
FINGERPRINT, not the live hash, so a stale env var never silently reverts an
in-app credential change; admin and OPDS credentials re-seed independently.
"""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USER
from foragerr.app import create_app
from foragerr.auth import sessions as S
from foragerr.auth.passwords import verify_password
from foragerr.config import Settings

_ORIGIN = {"Origin": "http://testserver"}


def _make_cfg(tmp_path: Path, name: str = "cfg") -> Path:
    cfg = tmp_path / name
    cfg.mkdir()
    return cfg


def _boot(cfg: Path):
    """A fresh app over ``cfg`` (reads the current env at construction time)."""
    return create_app(Settings(config_dir=cfg))


def _principal(cfg: Path):
    con = sqlite3.connect(cfg / "foragerr.db")
    try:
        return con.execute(
            "SELECT username, password_hash, opds_password_hash, api_key_sha256, "
            "env_password_hash, env_opds_password_hash FROM principal"
        ).fetchone()
    finally:
        con.close()


def _null_fingerprints(cfg: Path) -> None:
    """Simulate a v0.7.0 principal that predates the fingerprint columns."""
    con = sqlite3.connect(cfg / "foragerr.db")
    try:
        con.execute(
            "UPDATE principal SET env_password_hash = NULL, "
            "env_opds_password_hash = NULL"
        )
        con.commit()
    finally:
        con.close()


def _basic(user: str, password: str) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


# -- admin: stale env never reverts an in-app change --------------------------


@pytest.mark.req("FRG-AUTH-002")
def test_stale_env_does_not_revert_in_app_password_change(tmp_path):
    """In-app password change, then reboot with the ORIGINAL (stale) env pair:
    no re-seed, the live hash and the operator's session both survive."""
    cfg = _make_cfg(tmp_path)
    with TestClient(_boot(cfg)) as client:
        client.headers.pop("X-Api-Key", None)
        token = client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
        ).cookies[S.COOKIE_NAME]
        assert client.post(
            "/api/v1/auth/password",
            json={
                "current_password": TEST_ADMIN_PASSWORD,
                "new_password": "changed-in-app",
            },
            headers=_ORIGIN,
        ).status_code == 204
    live_after_change = _principal(cfg)[1]

    # Reboot with the env pair UNCHANGED (still TEST_ADMIN_PASSWORD) — stale.
    with TestClient(_boot(cfg)) as client2:
        client2.headers.pop("X-Api-Key", None)
        # No re-seed: the live hash is exactly the in-app one.
        assert _principal(cfg)[1] == live_after_change
        # The acting session is intact (invalidate_all was never called).
        assert client2.get(
            "/api/v1/auth/me", headers={"Cookie": f"{S.COOKIE_NAME}={token}"}
        ).status_code == 200
        # The in-app password logs in; the stale env password does NOT.
        assert client2.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": "changed-in-app"},
        ).status_code == 200
        assert client2.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
        ).status_code == 401


@pytest.mark.req("FRG-AUTH-002")
def test_changed_env_pair_reseeds_invalidates_and_updates_fingerprint(
    tmp_path, monkeypatch
):
    """A genuinely changed env pair still re-seeds: every session dies, the new
    password logs in, and the fingerprint is refreshed to the new env value."""
    cfg = _make_cfg(tmp_path)
    with TestClient(_boot(cfg)) as client:
        client.headers.pop("X-Api-Key", None)
        token = client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
        ).cookies[S.COOKIE_NAME]
    before = _principal(cfg)

    monkeypatch.setenv("FORAGERR_ADMIN_PASSWORD", "recovered-from-env")
    with TestClient(_boot(cfg)) as client2:
        client2.headers.pop("X-Api-Key", None)
        # All sessions were invalidated by the re-seed.
        assert client2.get(
            "/api/v1/auth/me", headers={"Cookie": f"{S.COOKIE_NAME}={token}"}
        ).status_code == 401
        assert client2.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": "recovered-from-env"},
        ).status_code == 200
    after = _principal(cfg)
    assert after[1] != before[1]  # live hash re-seeded
    assert after[4] != before[4]  # env_password_hash fingerprint refreshed
    assert verify_password("recovered-from-env", after[4])


# -- admin: NULL fingerprint upgrade (v0.7.0) ---------------------------------


@pytest.mark.req("FRG-AUTH-002")
def test_null_fingerprint_matching_env_records_without_reseed(tmp_path):
    """A v0.7.0 principal (NULL fingerprint) booted with a MATCHING env: the env
    is compared against the live hash once, no re-seed, fingerprint backfilled."""
    cfg = _make_cfg(tmp_path)
    with TestClient(_boot(cfg)):
        pass
    _null_fingerprints(cfg)
    before = _principal(cfg)
    assert before[4] is None and before[5] is None

    with TestClient(_boot(cfg)):
        pass
    after = _principal(cfg)
    assert after[1] == before[1]  # live hash untouched — no re-seed
    assert after[4] is not None  # fingerprint backfilled
    assert verify_password(TEST_ADMIN_PASSWORD, after[4])


@pytest.mark.req("FRG-AUTH-002")
def test_null_fingerprint_nonmatching_env_reseeds_once(tmp_path, monkeypatch):
    """A v0.7.0 principal (NULL fingerprint) booted with a NON-matching env
    re-seeds exactly once; a subsequent same-env boot is then a no-op."""
    cfg = _make_cfg(tmp_path)
    with TestClient(_boot(cfg)):
        pass
    _null_fingerprints(cfg)
    before = _principal(cfg)

    monkeypatch.setenv("FORAGERR_ADMIN_PASSWORD", "env-recovery")
    with TestClient(_boot(cfg)):
        pass
    after = _principal(cfg)
    assert after[1] != before[1]  # re-seeded to the env value
    assert verify_password("env-recovery", after[1])
    assert verify_password("env-recovery", after[4])  # fingerprint recorded

    # A second boot with the SAME env re-seeds nothing (idempotent thereafter).
    with TestClient(_boot(cfg)):
        pass
    assert _principal(cfg)[1] == after[1]


# -- OPDS: decoupled from admin ----------------------------------------------


@pytest.mark.req("FRG-AUTH-005")
def test_opds_env_change_reseeds_opds_only_no_session_wipe(tmp_path, monkeypatch):
    """A changed FORAGERR_OPDS_PASSWORD re-seeds ONLY the OPDS credential — the
    admin sessions are left untouched (OPDS is not a session credential)."""
    cfg = _make_cfg(tmp_path)
    monkeypatch.setenv("FORAGERR_OPDS_PASSWORD", "opds-original")
    with TestClient(_boot(cfg)) as client:
        client.headers.pop("X-Api-Key", None)
        token = client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
        ).cookies[S.COOKIE_NAME]

    monkeypatch.setenv("FORAGERR_OPDS_PASSWORD", "opds-rotated")
    with TestClient(_boot(cfg)) as client2:
        client2.headers.pop("X-Api-Key", None)
        # The admin session SURVIVES an OPDS-only re-seed.
        assert client2.get(
            "/api/v1/auth/me", headers={"Cookie": f"{S.COOKIE_NAME}={token}"}
        ).status_code == 200
        # OPDS Basic now takes the new password; the old one is refused.
        assert client2.get(
            "/opds", headers=_basic(TEST_ADMIN_USER, "opds-rotated")
        ).status_code == 200
        assert client2.get(
            "/opds", headers=_basic(TEST_ADMIN_USER, "opds-original")
        ).status_code == 401


@pytest.mark.req("FRG-AUTH-005")
def test_stale_opds_env_does_not_clobber_inapp_change_across_admin_reseed(
    tmp_path, monkeypatch
):
    """In-app OPDS change, then a reboot whose OPDS env is stale AND whose admin
    env is changed (forcing an admin re-seed): the admin re-seeds, but the
    in-app OPDS password is preserved — the stale OPDS env never clobbers it."""
    cfg = _make_cfg(tmp_path)
    monkeypatch.setenv("FORAGERR_OPDS_PASSWORD", "opds-original")
    with TestClient(_boot(cfg)) as client:
        # Change the OPDS password IN-APP (re-auth with the admin password).
        assert client.post(
            "/api/v1/auth/opds-password",
            json={
                "current_password": TEST_ADMIN_PASSWORD,
                "new_password": "opds-in-app",
            },
        ).status_code == 204

    # Reboot: OPDS env is STALE ("opds-original"); admin env changed to force a
    # decoupled admin re-seed in the same boot.
    monkeypatch.setenv("FORAGERR_ADMIN_PASSWORD", "admin-recovery")
    with TestClient(_boot(cfg)) as client2:
        client2.headers.pop("X-Api-Key", None)
        # Admin was re-seeded from the env.
        assert client2.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": "admin-recovery"},
        ).status_code == 200
        # Drop the login cookie so the OPDS Basic path is actually exercised
        # (a live cookie would authenticate regardless of the Basic header).
        client2.cookies.clear()
        # The in-app OPDS password survived; the stale env value did NOT win.
        assert client2.get(
            "/opds", headers=_basic(TEST_ADMIN_USER, "opds-in-app")
        ).status_code == 200
        assert client2.get(
            "/opds", headers=_basic(TEST_ADMIN_USER, "opds-original")
        ).status_code == 401
