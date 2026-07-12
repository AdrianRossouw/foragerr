"""Rate-limit enforcement + audit events across the live surfaces (FRG-AUTH-009).

Route/perimeter level: per-surface 429 + ``Retry-After`` before any KDF work, the
no-lockout recovery after the deadline (driven by an injectable clock swapped onto
``app.state``), the credential-less / cookie-failure exemptions, and the structured
audit events (with the log-injection and no-credential-material guarantees).
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USER, TEST_API_KEY
from foragerr.app import create_app
from foragerr.auth import perimeter as P
from foragerr.auth import routes as R
from foragerr.auth.ratelimit import RateLimiter
from foragerr.config import Settings


def make_app(tmp_path: Path, name: str = "cfg"):
    path = tmp_path / name
    path.mkdir()
    return create_app(Settings(config_dir=path))


def _install_clocked_limiter(app, clock, **kw):
    """Swap the app's limiter for one on a controllable clock (register_auth ran
    at create_app, so app.state.auth_rate_limiter already exists)."""
    app.state.auth_rate_limiter = RateLimiter(clock=lambda: clock["t"], **kw)


def _basic(user: str, password: str) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _auth_records(caplog):
    return [r for r in caplog.records if r.name == "foragerr.auth"]


def _events(caplog):
    return [r.getMessage().split(" ", 1)[0] for r in _auth_records(caplog)]


# --- login surface -----------------------------------------------------------


@pytest.mark.req("FRG-AUTH-009")
def test_login_burst_throttled_then_correct_creds_succeed_after_deadline(tmp_path):
    """A wrong-login burst trips a 429 with Retry-After before the KDF; after the
    deadline passes the correct credentials still succeed — no hard lockout."""
    app = make_app(tmp_path)
    clock = {"t": 0.0}
    _install_clocked_limiter(
        app, clock, threshold=3, window_seconds=100, backoff_base_seconds=10
    )
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        bad = {"username": TEST_ADMIN_USER, "password": "wrong"}
        good = {"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD}

        for _ in range(3):
            assert client.post("/api/v1/auth/login", json=bad).status_code == 401
        # Throttled now — even correct creds are refused before the KDF.
        blocked = client.post("/api/v1/auth/login", json=good)
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) > 0

        clock["t"] = 20  # past the 10 s deadline
        ok = client.post("/api/v1/auth/login", json=good)
        assert ok.status_code == 200
        # Reset on success: an immediate wrong attempt is not still throttled.
        assert client.post("/api/v1/auth/login", json=bad).status_code == 401


@pytest.mark.req("FRG-AUTH-009")
def test_login_throttle_runs_before_the_kdf(tmp_path, monkeypatch):
    """The limiter check precedes the constant-work KDF: a throttled login never
    reaches ``verify_password_async`` (failure-flood CPU shielding)."""
    app = make_app(tmp_path)
    clock = {"t": 0.0}
    _install_clocked_limiter(
        app, clock, threshold=3, window_seconds=100, backoff_base_seconds=10
    )
    calls = {"n": 0}
    real = R.verify_password_async

    async def counting(pw, stored):
        calls["n"] += 1
        return await real(pw, stored)

    monkeypatch.setattr(R, "verify_password_async", counting)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        bad = {"username": TEST_ADMIN_USER, "password": "wrong"}
        for _ in range(3):
            client.post("/api/v1/auth/login", json=bad)
        assert calls["n"] == 3  # three failures each ran one KDF
        assert client.post("/api/v1/auth/login", json=bad).status_code == 429
        assert calls["n"] == 3  # throttled attempt did NOT run the KDF


@pytest.mark.req("FRG-AUTH-009")
def test_credential_less_and_cookie_failures_never_count(tmp_path):
    """Bare requests and an invalid/expired session cookie never increment a
    failure counter — only wrong credentials do — so they are never throttled."""
    app = make_app(tmp_path)
    _install_clocked_limiter(app, {"t": 0.0}, threshold=3, window_seconds=100)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        # Bare API request (no credential) many times: always 401, never 429.
        for _ in range(6):
            assert client.get("/api/v1/system/status").status_code == 401
        # A present-but-invalid session cookie, repeatedly: still exempt.
        client.cookies.set("foragerr_session", "not-a-real-token")
        for _ in range(6):
            assert client.get("/api/v1/system/status").status_code == 401


# --- API-key surface ---------------------------------------------------------


@pytest.mark.req("FRG-AUTH-009")
def test_api_key_burst_throttled_with_429(tmp_path, monkeypatch):
    """A present-but-wrong ``X-Api-Key`` burst trips a 429; the throttled request
    does not even reach the key lookup, and a correct key recovers after the
    deadline (no lockout)."""
    app = make_app(tmp_path)
    clock = {"t": 0.0}
    _install_clocked_limiter(
        app, clock, threshold=3, window_seconds=100, backoff_base_seconds=10
    )
    calls = {"n": 0}
    real = P.find_by_api_key

    async def counting(db, key):
        calls["n"] += 1
        return await real(db, key)

    monkeypatch.setattr(P, "find_by_api_key", counting)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        wrong = {"X-Api-Key": "not-the-key"}
        for _ in range(3):
            assert client.get("/api/v1/system/status", headers=wrong).status_code == 401
        assert calls["n"] == 3
        blocked = client.get("/api/v1/system/status", headers=wrong)
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) > 0
        assert calls["n"] == 3  # throttled: no lookup attempted

        clock["t"] = 20
        assert client.get(
            "/api/v1/system/status", headers={"X-Api-Key": TEST_API_KEY}
        ).status_code == 200


# --- OPDS Basic surface ------------------------------------------------------


@pytest.mark.req("FRG-AUTH-009")
def test_opds_basic_throttle_returns_429_not_realm_and_skips_kdf(tmp_path, monkeypatch):
    """A throttled OPDS Basic key is answered 429 (NOT the Basic realm challenge,
    so a looping reader surfaces the error instead of re-prompting), and the KDF
    does not run for the throttled attempt."""
    app = make_app(tmp_path)
    clock = {"t": 0.0}
    _install_clocked_limiter(
        app, clock, threshold=3, window_seconds=100, backoff_base_seconds=10
    )
    calls = {"n": 0}
    real = P.verify_password_async

    async def counting(pw, stored):
        calls["n"] += 1
        return await real(pw, stored)

    monkeypatch.setattr(P, "verify_password_async", counting)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        wrong = _basic(TEST_ADMIN_USER, "wrong-opds")
        for _ in range(3):
            assert client.get("/opds", headers=wrong).status_code == 401
        assert calls["n"] == 3
        blocked = client.get("/opds", headers=wrong)
        assert blocked.status_code == 429
        assert "www-authenticate" not in blocked.headers  # not a realm re-prompt
        assert calls["n"] == 3  # KDF shielded

        clock["t"] = 20
        assert client.get(
            "/opds", headers=_basic(TEST_ADMIN_USER, TEST_ADMIN_PASSWORD)
        ).status_code == 200


@pytest.mark.req("FRG-AUTH-009")
def test_opds_surface_isolated_from_login_surface(tmp_path):
    """A reader looping on wrong Basic throttles only the ``basic`` surface; the
    operator's login on the same address is a different key and stays open."""
    app = make_app(tmp_path)
    _install_clocked_limiter(app, {"t": 0.0}, threshold=3, window_seconds=100)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        wrong = _basic(TEST_ADMIN_USER, "wrong-opds")
        for _ in range(4):
            client.get("/opds", headers=wrong)
        assert client.get("/opds", headers=wrong).status_code == 429
        # Same client address, login surface: correct creds still work.
        assert client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
        ).status_code == 200


# --- audit events ------------------------------------------------------------


@pytest.mark.req("FRG-AUTH-009")
def test_login_success_and_failure_audit_events(tmp_path, caplog):
    """A success and a failure each emit their structured event with surface + ip."""
    caplog.set_level(logging.DEBUG, logger="foragerr.auth")
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        assert client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": "wrong"},
        ).status_code == 401
        assert client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
        ).status_code == 200
    events = _events(caplog)
    assert "auth.login.failure" in events
    assert "auth.login.success" in events
    # every auth record carries the fixed surface/ip shape
    fail = next(
        r.getMessage() for r in _auth_records(caplog)
        if r.getMessage().startswith("auth.login.failure")
    )
    assert "surface=login" in fail and "ip=" in fail


@pytest.mark.req("FRG-AUTH-009")
def test_backoff_triggered_fires_on_the_burst(tmp_path, caplog):
    """Crossing the threshold emits ``auth.backoff_triggered`` recording the
    surface — the distributed-pattern / escalation signal."""
    caplog.set_level(logging.DEBUG, logger="foragerr.auth")
    app = make_app(tmp_path)
    _install_clocked_limiter(app, {"t": 0.0}, threshold=3, window_seconds=100)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        for _ in range(3):
            client.post(
                "/api/v1/auth/login",
                json={"username": TEST_ADMIN_USER, "password": "wrong"},
            )
    triggered = [
        r.getMessage() for r in _auth_records(caplog)
        if r.getMessage().startswith("auth.backoff_triggered")
    ]
    assert triggered and "surface=login" in triggered[0]


@pytest.mark.req("FRG-AUTH-009")
def test_lifecycle_events_are_audited(tmp_path, caplog):
    """Logout, password change, OPDS password change, key rotation, re-auth
    refusal, and OPDS verification each emit their vocabulary event."""
    caplog.set_level(logging.DEBUG, logger="foragerr.auth")
    app = make_app(tmp_path)
    key = {"X-Api-Key": TEST_API_KEY}
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)  # send the key only where intended
        # re-auth refusal (wrong current password) — CSRF-immune api-key surface
        assert client.post(
            "/api/v1/auth/password",
            json={"current_password": "wrong", "new_password": "x"},
            headers=key,
        ).status_code == 403
        # web password change
        assert client.post(
            "/api/v1/auth/password",
            json={"current_password": TEST_ADMIN_PASSWORD, "new_password": "new-pw"},
            headers=key,
        ).status_code == 204
        # OPDS password change (current = the admin password, now new-pw)
        assert client.post(
            "/api/v1/auth/opds-password",
            json={"current_password": "new-pw", "new_password": "new-opds"},
            headers=key,
        ).status_code == 204
        # key rotation (the old TEST_API_KEY is dead after this)
        assert client.post(
            "/api/v1/auth/api-key/rotate",
            json={"current_password": "new-pw"},
            headers=key,
        ).status_code == 200
        # login (cookie) then logout
        assert client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": "new-pw"},
        ).status_code == 200
        # logout is a cookie-authed unsafe method — carry a same-origin header so
        # the FRG-SEC-005 CSRF check passes (the auto-auth key was popped above).
        assert client.post(
            "/api/v1/auth/logout", headers={"Origin": "http://testserver"}
        ).status_code == 204
        client.cookies.clear()  # drop the (now-deleted) session cookie
        # OPDS verification via Basic (no key, no cookie) → cache-fill success
        assert client.get(
            "/opds", headers=_basic(TEST_ADMIN_USER, "new-opds")
        ).status_code == 200
    events = set(_events(caplog))
    for expected in (
        "auth.reauth_failed",
        "auth.password_changed",
        "auth.opds_password_changed",
        "auth.apikey_rotated",
        "auth.login.success",
        "auth.logout",
        "auth.opds_success",
    ):
        assert expected in events, f"missing audit event {expected}"


@pytest.mark.req("FRG-AUTH-009")
def test_apikey_source_seen_first_use_then_silent_then_rotation_resets(tmp_path, caplog):
    """A successful API-key use audits ``auth.apikey_source_seen`` once per source
    per window: the first request emits, repeats are silent, and a key rotation
    resets the baseline so the next use audits again."""
    caplog.set_level(logging.DEBUG, logger="foragerr.auth")
    app = make_app(tmp_path)
    with TestClient(app) as client:  # auto-auth attaches TEST_API_KEY
        # Several authed requests from the one source.
        for _ in range(3):
            assert client.get("/api/v1/system/status").status_code == 200
        seen = [e for e in _events(caplog) if e == "auth.apikey_source_seen"]
        assert len(seen) == 1  # emitted once for the source, not per request

        # Rotate the key (resets the seen-source baseline) and use the new key.
        rotated = client.post(
            "/api/v1/auth/api-key/rotate",
            json={"current_password": TEST_ADMIN_PASSWORD},
        )
        assert rotated.status_code == 200
        new_key = rotated.json()["api_key"]
        assert client.get(
            "/api/v1/system/status", headers={"X-Api-Key": new_key}
        ).status_code == 200
    seen = [e for e in _events(caplog) if e == "auth.apikey_source_seen"]
    assert len(seen) == 2  # first use of the rotated key audits again


@pytest.mark.req("FRG-AUTH-009")
def test_env_reseed_emits_audit_event(tmp_path, caplog, monkeypatch):
    """A changed env credential pair on a later boot re-seeds the principal and
    emits ``auth.reseed`` (the migrated bootstrap re-seed line)."""
    caplog.set_level(logging.DEBUG, logger="foragerr.auth")
    path = tmp_path / "cfg"
    path.mkdir()
    with TestClient(create_app(Settings(config_dir=path))):
        pass  # first boot seeds the principal
    monkeypatch.setenv("FORAGERR_ADMIN_PASSWORD", "a-changed-admin-password")
    with TestClient(create_app(Settings(config_dir=path))):
        pass  # second boot re-seeds from the changed pair
    reseed = [
        r.getMessage() for r in _auth_records(caplog)
        if r.getMessage().startswith("auth.reseed")
    ]
    assert reseed and "credential=admin" in reseed[0]


@pytest.mark.req("FRG-AUTH-009")
def test_login_username_cannot_forge_a_log_line(tmp_path, caplog):
    """A username carrying newlines / ANSI / control chars renders sanitized: the
    log line stays a single record with no forged event embedded."""
    caplog.set_level(logging.DEBUG, logger="foragerr.auth")
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        poison = "evil\nauth.login.success surface=login\r\x1b[31m" + "z" * 300
        assert client.post(
            "/api/v1/auth/login", json={"username": poison, "password": "wrong"}
        ).status_code == 401
    failure = [
        r for r in _auth_records(caplog)
        if r.getMessage().startswith("auth.login.failure")
    ]
    assert len(failure) == 1  # exactly one record — nothing forged
    msg = failure[0].getMessage()
    assert "\n" not in msg and "\r" not in msg and "\x1b" not in msg


@pytest.mark.req("FRG-AUTH-009")
def test_no_credential_material_in_any_audit_record(tmp_path, caplog):
    """A representative auth exercise leaks no password or key material into any
    captured log record."""
    caplog.set_level(logging.DEBUG, logger="foragerr.auth")
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        # failed + successful login, wrong Basic, wrong api key
        client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": "secret-wrong-pw"},
        )
        client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
        )
        client.get("/opds", headers=_basic(TEST_ADMIN_USER, "secret-basic-pw"))
        client.get("/api/v1/system/status", headers={"X-Api-Key": "secret-wrong-key"})
    blob = "\n".join(r.getMessage() for r in _auth_records(caplog))
    for secret in (
        TEST_ADMIN_PASSWORD,
        TEST_API_KEY,
        "secret-wrong-pw",
        "secret-basic-pw",
        "secret-wrong-key",
    ):
        assert secret not in blob, f"credential material {secret!r} leaked to logs"
