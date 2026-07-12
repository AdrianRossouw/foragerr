"""Password storage with a modern KDF (FRG-AUTH-003).

scrypt-only at rest, constant-time verify, fail-closed on tampered hashes, and
no credential material in logs across seed / login / failure / re-seed.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USER
from foragerr.app import create_app
from foragerr.auth.passwords import hash_password, verify_password
from foragerr.config import Settings


def make_app(tmp_path: Path, name: str = "cfg"):
    path = tmp_path / name
    path.mkdir()
    return create_app(Settings(config_dir=path)), path


@pytest.mark.req("FRG-AUTH-003")
def test_hash_is_self_describing_scrypt_with_unique_salts():
    a = hash_password("correct horse")
    b = hash_password("correct horse")
    assert a.startswith("scrypt$")
    assert a != b  # unique per-credential salt -> distinct hashes for same input
    # scrypt$n$r$p$salt$hash — six fields
    assert len(a.split("$")) == 6


@pytest.mark.req("FRG-AUTH-003")
def test_verify_accepts_correct_rejects_wrong():
    stored = hash_password("s3cret-passphrase")
    assert verify_password("s3cret-passphrase", stored) is True
    assert verify_password("s3cret-passphras", stored) is False
    assert verify_password("", stored) is False
    assert verify_password("S3CRET-PASSPHRASE", stored) is False


@pytest.mark.req("FRG-AUTH-003")
def test_tampered_or_truncated_hash_fails_closed():
    stored = hash_password("pw")
    # Truncation, garbage, empty, and a flipped hash byte all reject (never raise
    # into acceptance).
    assert verify_password("pw", stored[:-4]) is False
    assert verify_password("pw", "not-a-hash") is False
    assert verify_password("pw", "") is False
    assert verify_password("pw", "scrypt$0$8$1$AAAA$AAAA") is False  # bad n
    scheme, n, r, p, salt, h = stored.split("$")
    flipped = h[:-1] + ("A" if h[-1] != "A" else "B")
    assert verify_password("pw", "$".join((scheme, n, r, p, salt, flipped))) is False


@pytest.mark.req("FRG-AUTH-003")
def test_only_scrypt_hashes_at_rest_after_seed(tmp_path):
    """The DB stores scrypt hashes only — never plaintext, for either password."""
    app, cfg = make_app(tmp_path)
    with TestClient(app):
        pass
    con = sqlite3.connect(cfg / "foragerr.db")
    try:
        row = con.execute(
            "SELECT password_hash, opds_password_hash, api_key_sha256 FROM principal"
        ).fetchone()
    finally:
        con.close()
    password_hash, opds_hash, api_sha = row
    assert password_hash.startswith("scrypt$")
    assert opds_hash.startswith("scrypt$")
    # No plaintext anywhere; the API key is a bare SHA-256 hex (64 chars).
    assert TEST_ADMIN_PASSWORD not in password_hash
    assert TEST_ADMIN_PASSWORD not in opds_hash
    assert len(api_sha) == 64 and all(c in "0123456789abcdef" for c in api_sha)
    # The seeded hash verifies against the real password.
    assert verify_password(TEST_ADMIN_PASSWORD, password_hash) is True


@pytest.mark.req("FRG-AUTH-003")
def test_no_credential_material_in_logs_across_lifecycle(tmp_path, caplog):
    """Seed + login + failed login + re-seed emit no password/hash/salt material."""
    caplog.set_level(logging.DEBUG)
    app, cfg = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        # successful + failed login
        client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
        )
        client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": "wrong-password"},
        )
    # re-seed via a changed env pair on a second boot over the same dir
    import os

    os.environ["FORAGERR_ADMIN_PASSWORD"] = "a-different-admin-password"
    try:
        app2 = create_app(Settings(config_dir=cfg))
        with TestClient(app2):
            pass
    finally:
        os.environ["FORAGERR_ADMIN_PASSWORD"] = TEST_ADMIN_PASSWORD

    blob = "\n".join(rec.getMessage() for rec in caplog.records)
    for secret in (
        TEST_ADMIN_PASSWORD,
        "wrong-password",
        "a-different-admin-password",
    ):
        assert secret not in blob, f"credential material {secret!r} leaked to logs"
    # nor any raw scrypt hash / salt
    assert "scrypt$" not in blob
