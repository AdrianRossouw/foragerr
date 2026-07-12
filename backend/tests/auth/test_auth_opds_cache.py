"""OPDS Basic verify-cache: positive-only, TTL-bounded, cleared on any
credential write (FRG-AUTH-005)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USER, TEST_API_KEY
from foragerr.app import create_app
from foragerr.auth import perimeter as P
from foragerr.auth.perimeter import OpdsVerifyCache
from foragerr.config import Settings


def make_app(tmp_path: Path, name: str = "cfg"):
    path = tmp_path / name
    path.mkdir()
    return create_app(Settings(config_dir=path))


def _basic(user: str, password: str) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def verify_counter(monkeypatch):
    """Count every scrypt OPDS verify the perimeter runs (cache misses only)."""
    calls = {"n": 0}
    real = P.verify_password_async

    async def counting(password, stored):
        calls["n"] += 1
        return await real(password, stored)

    monkeypatch.setattr(P, "verify_password_async", counting)
    return calls


@pytest.mark.req("FRG-AUTH-005")
def test_repeat_creds_hit_cache_and_skip_the_kdf(tmp_path, verify_counter):
    """A second OPDS request with the same correct creds is served from the
    cache without re-running the scrypt verify."""
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        headers = _basic(TEST_ADMIN_USER, TEST_ADMIN_PASSWORD)
        assert client.get("/opds", headers=headers).status_code == 200
        assert verify_counter["n"] == 1  # first attempt ran the KDF
        assert client.get("/opds", headers=headers).status_code == 200
        assert verify_counter["n"] == 1  # second attempt was a cache hit


@pytest.mark.req("FRG-AUTH-005")
def test_wrong_creds_are_never_cached_and_always_run_the_kdf(tmp_path, verify_counter):
    """A failed verify is never cached: each wrong attempt re-runs the KDF, and a
    wrong USERNAME with a correct password still pays the KDF (no timing oracle)."""
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        wrong_pw = _basic(TEST_ADMIN_USER, "not-the-opds-password")
        assert client.get("/opds", headers=wrong_pw).status_code == 401
        first = verify_counter["n"]
        assert client.get("/opds", headers=wrong_pw).status_code == 401
        assert verify_counter["n"] == first + 1  # ran again — never cached

        # Wrong username + correct password: still refused, still runs the KDF.
        before = verify_counter["n"]
        assert client.get(
            "/opds", headers=_basic("not-the-user", TEST_ADMIN_PASSWORD)
        ).status_code == 401
        assert verify_counter["n"] == before + 1


@pytest.mark.req("FRG-AUTH-005")
def test_opds_password_change_clears_cache_old_creds_401_immediately(tmp_path):
    """Changing the OPDS password clears the verify-cache so a previously-cached
    positive for the old password cannot linger — the old creds 401 at once."""
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        old = _basic(TEST_ADMIN_USER, TEST_ADMIN_PASSWORD)
        # Prime the cache with a successful verify.
        assert client.get("/opds", headers=old).status_code == 200
        # Change the OPDS password over the API-key surface (CSRF-immune).
        assert client.post(
            "/api/v1/auth/opds-password",
            json={
                "current_password": TEST_ADMIN_PASSWORD,
                "new_password": "rotated-opds",
            },
            headers={"X-Api-Key": TEST_API_KEY},
        ).status_code == 204
        # The stale positive is gone: old creds fail, the new ones work.
        assert client.get("/opds", headers=old).status_code == 401
        assert client.get(
            "/opds", headers=_basic(TEST_ADMIN_USER, "rotated-opds")
        ).status_code == 200


@pytest.mark.req("FRG-AUTH-005")
def test_admin_password_change_clears_cache(tmp_path, verify_counter):
    """An admin web-password change also clears the OPDS verify-cache (any
    credential write does): the next OPDS request re-runs the KDF."""
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        headers = _basic(TEST_ADMIN_USER, TEST_ADMIN_PASSWORD)
        assert client.get("/opds", headers=headers).status_code == 200
        primed = verify_counter["n"]
        # Change the admin password (does not alter the OPDS password).
        assert client.post(
            "/api/v1/auth/password",
            json={
                "current_password": TEST_ADMIN_PASSWORD,
                "new_password": "new-admin-pw",
            },
            headers={"X-Api-Key": TEST_API_KEY},
        ).status_code == 204
        # Cache was cleared: the same OPDS creds re-run the verify (still valid).
        assert client.get("/opds", headers=headers).status_code == 200
        assert verify_counter["n"] == primed + 1


# -- unit: cache mechanics ----------------------------------------------------


@pytest.mark.req("FRG-AUTH-005")
def test_cache_ttl_and_capacity_and_isolation():
    """Positive entries expire on the TTL, capacity evicts oldest-first, and a
    distinct username never collides with another's slot."""
    clock = {"t": 1000.0}
    cache = OpdsVerifyCache(ttl_seconds=60.0, capacity=2, clock=lambda: clock["t"])

    cache.put("admin", "pw", 1, generation=cache.generation())
    assert cache.get("admin", "pw") == 1
    # Distinct presented creds get distinct keys (no cross-user hit).
    assert cache.get("admin", "other") is None
    assert cache.get("someone", "pw") is None

    # TTL expiry.
    clock["t"] = 1061.0
    assert cache.get("admin", "pw") is None

    # Capacity: a third insert evicts the oldest.
    clock["t"] = 2000.0
    g = cache.generation()
    cache.put("a", "1", 1, generation=g)
    cache.put("b", "2", 2, generation=g)
    cache.put("c", "3", 3, generation=g)  # evicts "a"
    assert cache.get("a", "1") is None
    assert cache.get("b", "2") == 2
    assert cache.get("c", "3") == 3

    cache.clear()
    assert cache.get("b", "2") is None


@pytest.mark.req("FRG-AUTH-005")
def test_put_is_dropped_when_a_clear_intervenes_toctou():
    """A verify that captured its generation BEFORE a concurrent credential write
    (clear) must not re-seed its now-stale positive: put() with the old
    generation is a no-op, so the old creds cannot linger for the TTL."""
    cache = OpdsVerifyCache(ttl_seconds=60.0, capacity=8)

    # Reader captures the generation, then its KDF "awaits" — during which a
    # credential change clears the cache (advancing the generation).
    gen = cache.generation()
    cache.clear()  # the OPDS/admin password just changed mid-verify

    # The reader resumes and tries to cache its (now stale) positive.
    cache.put("admin", "old-pw", 1, generation=gen)
    assert cache.get("admin", "old-pw") is None  # dropped — not resurrected

    # A verify that starts AFTER the clear caches normally.
    cache.put("admin", "new-pw", 1, generation=cache.generation())
    assert cache.get("admin", "new-pw") == 1


@pytest.mark.req("FRG-AUTH-005")
def test_cache_key_is_length_unambiguous():
    """Field-boundary shifts never collide onto another entry's slot: ("a\\0b","c")
    and ("a","b\\0c") are distinct keys (the digest-of-digests join, not a raw
    NUL join)."""
    cache = OpdsVerifyCache(ttl_seconds=60.0, capacity=8)
    cache.put("a\x00b", "c", 1, generation=cache.generation())
    assert cache.get("a", "b\x00c") is None
    assert cache.get("a\x00b", "c") == 1
