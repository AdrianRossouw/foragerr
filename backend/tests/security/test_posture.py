"""Deployment-posture perimeter tests: security response headers
(FRG-SEC-006), opt-in trusted-proxy handling (FRG-SEC-007), and
disclosure/error hygiene (FRG-SEC-008)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USER
from foragerr.api.posture import TrustedProxyMiddleware, _parse_trusted
from foragerr.app import create_app
from foragerr.config import Settings


@pytest.fixture
def app(tmp_path):
    path = tmp_path / "cfg"
    path.mkdir()
    return create_app(Settings(config_dir=path))


@pytest.fixture
def proxied_app(tmp_path):
    """An app that trusts the TestClient's fixed peer address as its proxy."""
    path = tmp_path / "cfg"
    path.mkdir()
    return create_app(Settings(config_dir=path, trusted_proxies="testclient"))


# -- FRG-SEC-006: security response headers -----------------------------------

_BASELINE = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
    "x-frame-options": "DENY",
}


def _assert_baseline(response):
    for name, value in _BASELINE.items():
        assert response.headers.get(name) == value, name
    assert "content-security-policy" in response.headers


@pytest.mark.req("FRG-SEC-006")
def test_headers_on_every_surface_and_status(app):
    """Baseline headers appear on data responses, auth rejections, 404s, and
    the SPA document alike — the middleware is outermost by construction."""
    with TestClient(app) as client:
        authed = client.get("/api/v1/system/status")
        health = client.get("/health")
        missing = client.get("/api/v1/series/999999")
        spa = client.get("/")
        client.headers.pop("X-Api-Key", None)
        rejected = client.get("/api/v1/system/status")

    for response in (authed, health, missing, spa, rejected):
        _assert_baseline(response)
    assert rejected.status_code == 401

    # Data surfaces carry the deny-everything document policy; the SPA
    # document carries the self-only policy.
    assert health.headers["content-security-policy"].startswith("default-src 'none'")
    assert "frame-ancestors 'none'" in health.headers["content-security-policy"]
    assert spa.headers["content-security-policy"].startswith("default-src 'self'")
    assert "frame-ancestors 'none'" in spa.headers["content-security-policy"]


@pytest.mark.req("FRG-SEC-006")
def test_spa_policy_permits_no_external_origin(app):
    with TestClient(app) as client:
        spa = client.get("/")
    policy = spa.headers["content-security-policy"]
    for directive in policy.split(";"):
        for token in directive.split()[1:]:
            assert not token.startswith("http"), f"external origin in CSP: {token}"
            assert not token.startswith("*"), f"wildcard origin in CSP: {token}"


@pytest.mark.req("FRG-SEC-006")
def test_no_cors_surface_exists(app):
    """Same-origin only, by position: no Access-Control-Allow-* header is
    ever emitted — not for a cross-origin GET, not for a preflight."""
    with TestClient(app) as client:
        got = client.get("/health", headers={"Origin": "https://evil.example"})
        preflight = client.options(
            "/api/v1/system/status",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )
    for response in (got, preflight):
        for name in response.headers:
            assert not name.lower().startswith("access-control-"), name


# -- FRG-SEC-007: opt-in trusted proxy ----------------------------------------


class _CaptureApp:
    """A terminal ASGI app recording the scope it was called with."""

    def __init__(self) -> None:
        self.scope = None

    async def __call__(self, scope, receive, send) -> None:
        self.scope = scope
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


def _run(middleware, scope) -> None:
    async def _receive():  # pragma: no cover - never called
        return {"type": "http.request"}

    async def _send(_message) -> None:
        return None

    asyncio.run(middleware(scope, _receive, _send))


def _scope(client_host: str, headers: list[tuple[bytes, bytes]]) -> dict:
    return {
        "type": "http",
        "scheme": "http",
        "path": "/api/v1/x",
        "method": "GET",
        "client": (client_host, 40000),
        "headers": headers,
    }


@pytest.mark.req("FRG-SEC-007")
def test_trusted_peer_resolves_scheme_and_client():
    inner = _CaptureApp()
    middleware = TrustedProxyMiddleware(inner, trusted_proxies=frozenset({"10.0.0.2"}))
    _run(
        middleware,
        _scope(
            "10.0.0.2",
            [
                (b"x-forwarded-proto", b"https"),
                (b"x-forwarded-for", b"203.0.113.7, 10.0.0.2"),
            ],
        ),
    )
    assert inner.scope["scheme"] == "https"
    assert inner.scope["client"][0] == "203.0.113.7"


@pytest.mark.req("FRG-SEC-007")
def test_untrusted_peer_headers_are_ignored():
    """The negative path: forwarded headers from a peer NOT on the list do
    nothing — scheme and client stay the direct connection's."""
    inner = _CaptureApp()
    middleware = TrustedProxyMiddleware(inner, trusted_proxies=frozenset({"10.0.0.2"}))
    _run(
        middleware,
        _scope(
            "198.51.100.9",
            [
                (b"x-forwarded-proto", b"https"),
                (b"x-forwarded-for", b"203.0.113.7"),
            ],
        ),
    )
    assert inner.scope["scheme"] == "http"
    assert inner.scope["client"][0] == "198.51.100.9"


@pytest.mark.req("FRG-SEC-007")
def test_empty_setting_never_consults_headers():
    inner = _CaptureApp()
    middleware = TrustedProxyMiddleware(inner, trusted_proxies=_parse_trusted(""))
    _run(
        middleware,
        _scope("10.0.0.2", [(b"x-forwarded-proto", b"https")]),
    )
    assert inner.scope["scheme"] == "http"


@pytest.mark.req("FRG-SEC-007")
def test_forwarded_chain_skips_trusted_entries():
    """XFF ``client, proxyB`` with both proxies trusted resolves to the real
    client, not an intermediate hop."""
    inner = _CaptureApp()
    middleware = TrustedProxyMiddleware(
        inner, trusted_proxies=frozenset({"10.0.0.2", "10.0.0.3"})
    )
    _run(
        middleware,
        _scope(
            "10.0.0.2",
            [(b"x-forwarded-for", b"203.0.113.7, 10.0.0.3")],
        ),
    )
    assert inner.scope["client"][0] == "203.0.113.7"


@pytest.mark.req("FRG-SEC-007")
def test_duplicate_forwarded_headers_join_in_field_order():
    """A proxy emitting its XFF contribution as a SEPARATE header (not an
    append) must still win: values are comma-joined in field order, so the
    proxy's entry is rightmost and the attacker's separate header loses."""
    inner = _CaptureApp()
    middleware = TrustedProxyMiddleware(inner, trusted_proxies=frozenset({"10.0.0.2"}))
    _run(
        middleware,
        _scope(
            "10.0.0.2",
            [
                (b"x-forwarded-for", b"198.51.100.99"),  # attacker-supplied
                (b"x-forwarded-for", b"203.0.113.7"),  # proxy-observed, separate header
            ],
        ),
    )
    assert inner.scope["client"][0] == "203.0.113.7"


@pytest.mark.req("FRG-SEC-007")
def test_malformed_forwarded_entry_fails_closed():
    """A non-IP entry can never become a rate-limit key or audit ip= field —
    resolution stops and the direct peer stands."""
    inner = _CaptureApp()
    middleware = TrustedProxyMiddleware(inner, trusted_proxies=frozenset({"10.0.0.2"}))
    _run(
        middleware,
        _scope(
            "10.0.0.2",
            [(b"x-forwarded-for", b'198.51.100.7 surface=api_key ip="fake"')],
        ),
    )
    assert inner.scope["client"][0] == "10.0.0.2"  # untouched direct peer


@pytest.mark.req("FRG-SEC-007")
def test_ipv6_and_port_forms_normalize():
    inner = _CaptureApp()
    middleware = TrustedProxyMiddleware(inner, trusted_proxies=frozenset({"10.0.0.2"}))
    _run(
        middleware,
        _scope("10.0.0.2", [(b"x-forwarded-for", b"[2001:db8::7]:443")]),
    )
    assert inner.scope["client"][0] == "2001:db8::7"

    inner2 = _CaptureApp()
    middleware2 = TrustedProxyMiddleware(inner2, trusted_proxies=frozenset({"10.0.0.2"}))
    _run(
        middleware2,
        _scope("10.0.0.2", [(b"x-forwarded-for", b"203.0.113.9:41000")]),
    )
    assert inner2.scope["client"][0] == "203.0.113.9"


@pytest.mark.req("FRG-SEC-007")
def test_ws_proto_rejected_on_http_scope():
    """ws/wss are not valid X-Forwarded-Proto values for an HTTP request; a
    misconfigured trusted proxy must not silently clear the Secure decision."""
    inner = _CaptureApp()
    middleware = TrustedProxyMiddleware(inner, trusted_proxies=frozenset({"10.0.0.2"}))
    _run(middleware, _scope("10.0.0.2", [(b"x-forwarded-proto", b"wss")]))
    assert inner.scope["scheme"] == "http"


@pytest.mark.req("FRG-SEC-007")
def test_websocket_scope_resolves_scheme_and_client():
    """The websocket scope gets the same resolution, with the https→wss remap,
    so WS audit attribution matches HTTP."""
    inner = _CaptureApp()
    middleware = TrustedProxyMiddleware(inner, trusted_proxies=frozenset({"10.0.0.2"}))
    scope = _scope(
        "10.0.0.2",
        [
            (b"x-forwarded-proto", b"https"),
            (b"x-forwarded-for", b"203.0.113.7"),
        ],
    )
    scope["type"] = "websocket"
    scope["scheme"] = "ws"
    _run(middleware, scope)
    assert inner.scope["scheme"] == "wss"
    assert inner.scope["client"][0] == "203.0.113.7"


@pytest.mark.req("FRG-SEC-007")
def test_attacker_prepended_proto_entry_loses():
    """XFP takes the LAST entry (nearest trusted hop); a client-prepended
    duplicate or extra entry never decides the effective scheme."""
    inner = _CaptureApp()
    middleware = TrustedProxyMiddleware(inner, trusted_proxies=frozenset({"10.0.0.2"}))
    _run(
        middleware,
        _scope(
            "10.0.0.2",
            [
                (b"x-forwarded-proto", b"https"),  # attacker-supplied header
                (b"x-forwarded-proto", b"http"),  # proxy's own observation
            ],
        ),
    )
    assert inner.scope["scheme"] == "http"


@pytest.mark.req("FRG-SEC-007")
def test_env_var_binds_the_setting(tmp_path, monkeypatch):
    path = tmp_path / "cfg-env"
    path.mkdir()
    monkeypatch.setenv("FORAGERR_TRUSTED_PROXIES", "10.9.9.9, proxyhost")
    settings = Settings(config_dir=path)
    assert settings.trusted_proxies == "10.9.9.9, proxyhost"
    assert settings.trusted_proxy_set() == frozenset({"10.9.9.9", "proxyhost"})


@pytest.mark.req("FRG-SEC-007")
def test_secure_cookie_set_behind_trusted_proxy(proxied_app):
    """End to end through the real app: the TestClient peer is configured as
    the trusted proxy, X-Forwarded-Proto https → login cookies carry Secure;
    the rate limiter and audit read the same resolved scope by construction
    (they key on ``scope[\"client\"]``, rewritten before they run)."""
    with TestClient(proxied_app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={
                "username": TEST_ADMIN_USER,
                "password": TEST_ADMIN_PASSWORD,
                "remember": False,
            },
            headers={"X-Forwarded-Proto": "https"},
        )
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert "Secure" in set_cookie


@pytest.mark.req("FRG-SEC-007")
def test_no_secure_cookie_without_trust(app):
    """Same forwarded header, but the setting is empty: the header is ignored
    and the plain-HTTP login cookie stays non-Secure (the pre-M10 posture)."""
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={
                "username": TEST_ADMIN_USER,
                "password": TEST_ADMIN_PASSWORD,
                "remember": False,
            },
            headers={"X-Forwarded-Proto": "https"},
        )
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert "Secure" not in set_cookie


@pytest.mark.req("FRG-SEC-007")
def test_audit_attribution_uses_forwarded_client(proxied_app, caplog):
    """End-to-end proof of the consumer-agreement scenario's client half: a
    failed login through the trusted proxy is audited (and therefore
    throttle-keyed — same client_ip call) against the FORWARDED address, not
    the direct peer."""
    import logging as _logging

    with TestClient(proxied_app) as client:
        with caplog.at_level(_logging.INFO, logger="foragerr.auth"):
            response = client.post(
                "/api/v1/auth/login",
                json={"username": TEST_ADMIN_USER, "password": "wrong", "remember": False},
                headers={"X-Forwarded-For": "203.0.113.77"},
            )
    assert response.status_code == 401
    auth_lines = [r.getMessage() for r in caplog.records if "auth.login.failure" in r.getMessage()]
    assert auth_lines, "expected an auth.login.failure audit event"
    assert any("ip=203.0.113.77" in line for line in auth_lines)
    assert not any("ip=testclient" in line for line in auth_lines)


@pytest.mark.req("FRG-SEC-006")
def test_opds_surface_carries_data_policy(app):
    """The OPDS 401 (a real reader's first contact) carries the deny-all data
    CSP and keeps its Basic challenge."""
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        response = client.get("/opds")
    assert response.status_code == 401
    _assert_baseline(response)
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert "Basic" in response.headers.get("www-authenticate", "")


@pytest.mark.req("FRG-SEC-006")
def test_custom_opds_base_path_keeps_data_policy(tmp_path):
    """A reconfigured opds_base_path must not demote OPDS to the SPA policy —
    the classifier reads the setting, not a literal."""
    path = tmp_path / "cfg-opds"
    path.mkdir()
    custom = create_app(Settings(config_dir=path, opds_base_path="/catalog"))
    with TestClient(custom) as client:
        client.headers.pop("X-Api-Key", None)
        moved = client.get("/catalog")
        spa_like = client.get("/opdsx")  # boundary: NOT the opds base
    assert moved.headers["content-security-policy"].startswith("default-src 'none'")
    assert spa_like.headers["content-security-policy"].startswith("default-src 'self'")


# -- FRG-SEC-008: disclosure and error hygiene --------------------------------


@pytest.mark.req("FRG-SEC-008")
@pytest.mark.req("FRG-SEC-006")
def test_unhandled_error_is_generic_with_headers(app, monkeypatch):
    """A handler blowing up yields the uniform envelope with a generic
    message — no traceback, exception class, or path — and still carries the
    security headers (the hygiene middleware is outermost)."""

    async def _boom(_app):
        raise RuntimeError("secret detail: /config/foragerr.db exploded")

    monkeypatch.setattr("foragerr.api.health.probe_components", _boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers.pop("X-Api-Key", None)
        response = client.get("/health")

    assert response.status_code == 500
    assert response.json() == {"message": "Internal server error", "errors": []}
    assert "RuntimeError" not in response.text
    assert "secret detail" not in response.text
    assert "foragerr.db" not in response.text
    assert "Traceback" not in response.text
    _assert_baseline(response)


@pytest.mark.req("FRG-SEC-008")
def test_mid_stream_failure_reraises_without_second_start():
    """An exception AFTER http.response.start cannot be converted into a 500 —
    the middleware re-raises and never emits a second response start."""
    import asyncio

    from foragerr.api.posture import SecurityHeadersMiddleware

    async def exploding_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("mid-stream failure")

    sent = []

    async def _recording_send(message):
        sent.append(message)

    async def _receive():  # pragma: no cover - never called
        return {"type": "http.request"}

    middleware = SecurityHeadersMiddleware(exploding_app)
    scope = {"type": "http", "method": "GET", "path": "/api/v1/x", "headers": []}
    with pytest.raises(RuntimeError, match="mid-stream failure"):
        asyncio.run(middleware(scope, _receive, _recording_send))
    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert len(starts) == 1  # the original start, stamped — never a second
    assert any(k == b"content-security-policy" for k, _ in starts[0]["headers"])


@pytest.mark.req("FRG-SEC-008")
def test_no_debug_disclosure_path_exists(app):
    """No debug flag can widen error disclosure: the app is built with
    debug off and the configuration surface has no debug switch."""
    assert app.debug is False
    assert "debug" not in Settings.model_fields
    for field in Settings.model_fields:
        assert "debug" not in field.lower()
