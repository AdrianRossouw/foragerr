"""Env bootstrap of the principal (FRG-AUTH-002): fail-fast, seed, re-seed,
idempotency, and the one-shot bootstrap-key surfacing."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USER, TEST_API_KEY
from foragerr.app import create_app
from foragerr.config import ConfigError, Settings


def _principal_row(cfg: Path):
    con = sqlite3.connect(cfg / "foragerr.db")
    try:
        return con.execute(
            "SELECT username, password_hash, opds_password_hash, api_key_sha256 "
            "FROM principal"
        ).fetchall()
    finally:
        con.close()


@pytest.mark.req("FRG-AUTH-002")
def test_fail_fast_without_admin_pair_on_empty_db(tmp_path, monkeypatch):
    """First boot with no principal and no admin env pair refuses to start —
    a ConfigError before migrations/serving (the non-zero-exit path)."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.delenv("FORAGERR_ADMIN_USER", raising=False)
    monkeypatch.delenv("FORAGERR_ADMIN_PASSWORD", raising=False)
    with pytest.raises(ConfigError) as exc:
        create_app(Settings(config_dir=cfg))
    message = str(exc.value)
    assert "FORAGERR_ADMIN_USER" in message
    assert "FORAGERR_ADMIN_PASSWORD" in message
    # Nothing was written: no database file created before the gate.
    assert not (cfg / "foragerr.db").exists()


@pytest.mark.req("FRG-AUTH-002")
def test_empty_pair_also_fails_fast(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("FORAGERR_ADMIN_USER", "")
    monkeypatch.setenv("FORAGERR_ADMIN_PASSWORD", "")
    with pytest.raises(ConfigError):
        create_app(Settings(config_dir=cfg))


@pytest.mark.req("FRG-AUTH-002")
def test_seed_creates_principal_opds_and_key_hash(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(Settings(config_dir=cfg))
    with TestClient(app):
        assert app.state.bootstrap_api_key == TEST_API_KEY
    rows = _principal_row(cfg)
    assert len(rows) == 1
    username, pw_hash, opds_hash, api_sha = rows[0]
    assert username == TEST_ADMIN_USER
    assert pw_hash.startswith("scrypt$") and opds_hash.startswith("scrypt$")
    assert len(api_sha) == 64  # SHA-256 hex of the raw key


@pytest.mark.req("FRG-AUTH-002")
def test_opds_password_from_env_when_set(tmp_path, monkeypatch):
    """FORAGERR_OPDS_PASSWORD seeds an OPDS password independent of admin's."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("FORAGERR_OPDS_PASSWORD", "separate-opds-password")
    app = create_app(Settings(config_dir=cfg))
    import base64

    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)

        def basic(pw: str) -> dict:
            token = base64.b64encode(f"{TEST_ADMIN_USER}:{pw}".encode()).decode()
            return {"Authorization": f"Basic {token}"}

        # The OPDS password is the env one, NOT the admin password.
        assert client.get("/opds", headers=basic("separate-opds-password")).status_code == 200
        assert client.get("/opds", headers=basic(TEST_ADMIN_PASSWORD)).status_code == 401


@pytest.mark.req("FRG-AUTH-002")
def test_idempotent_on_unchanged_boot(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    with TestClient(create_app(Settings(config_dir=cfg))):
        pass
    before = _principal_row(cfg)
    # Second boot, same env pair: nothing changes.
    with TestClient(create_app(Settings(config_dir=cfg))):
        pass
    after = _principal_row(cfg)
    assert before == after  # same username, hashes, key hash


@pytest.mark.req("FRG-AUTH-002")
def test_changed_pair_reseeds_and_leaves_a_working_login(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    with TestClient(create_app(Settings(config_dir=cfg))):
        pass
    before = _principal_row(cfg)[0]

    os.environ["FORAGERR_ADMIN_PASSWORD"] = "recovered-admin-password"
    try:
        app2 = create_app(Settings(config_dir=cfg))
        with TestClient(app2) as client:
            client.headers.pop("X-Api-Key", None)
            # The NEW password logs in; the OLD one does not.
            assert client.post(
                "/api/v1/auth/login",
                json={"username": TEST_ADMIN_USER, "password": "recovered-admin-password"},
            ).status_code == 200
            assert client.post(
                "/api/v1/auth/login",
                json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
            ).status_code == 401
    finally:
        os.environ["FORAGERR_ADMIN_PASSWORD"] = TEST_ADMIN_PASSWORD

    after = _principal_row(cfg)[0]
    assert after[1] != before[1]  # password hash changed (re-seed)


@pytest.mark.req("FRG-AUTH-002")
def test_bootstrap_key_endpoint_is_one_shot(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(Settings(config_dir=cfg))
    with TestClient(app) as client:
        # first authenticated read returns the key, then 404 forever
        first = client.get("/api/v1/auth/bootstrap-key")
        assert first.status_code == 200
        assert first.json()["api_key"] == TEST_API_KEY
        assert client.get("/api/v1/auth/bootstrap-key").status_code == 404


@pytest.mark.req("FRG-AUTH-002")
def test_bootstrap_key_absent_after_restart(tmp_path):
    """A restart clears the in-memory notice — the key is 404 on the next boot
    (it was never persisted plaintext)."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    with TestClient(create_app(Settings(config_dir=cfg))):
        pass
    # Second boot over the existing principal: no key minted, endpoint 404s.
    app2 = create_app(Settings(config_dir=cfg))
    with TestClient(app2) as client:
        assert client.get("/api/v1/auth/bootstrap-key").status_code == 404
