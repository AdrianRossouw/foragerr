"""AUTH-001: no auth exists in M1 — route inventory, credential-free
surfaces, and no dormant auth code paths (FRG-AUTH-001)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import routing
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "backend" / "src"

#: Real auth-shaped constructs — route paths, security classes, middleware,
#: current-user dependencies. Deliberately NOT single generic words like
#: "password"/"secret"/"token": those appear legitimately in this codebase's
#: own log-redaction machinery (FRG-NFR-008) and third-party API-key config
#: fields, neither of which is user-authentication.
_AUTH_SMELL_RE = re.compile(
    r"(?i)"
    r"(\bdef\s+(login|logout|authenticate)\b"
    r"|\bclass\s+\w*(Login|Session|AuthMiddleware)\w*\b"
    r"|@\w+\.(get|post)\(\s*[\"']/[^\"']*(login|logout)"
    r"|\bOAuth2PasswordBearer\b|\bHTTPBasic\b|\bHTTPBearer\b"
    r"|\bSessionMiddleware\b|\bAuthenticationMiddleware\b"
    r"|Depends\(\s*(get_current_user|require_auth|authenticate)\b"
    r"|\bpassword_hash\b|\bcredential[_-]?store\b)"
)


def make_app(tmp_path, name: str):
    path = tmp_path / name
    path.mkdir()
    return create_app(Settings(config_dir=path))


@pytest.mark.req("FRG-AUTH-001")
@pytest.mark.req("FRG-NFR-014")
def test_only_the_resource_limit_middleware_is_registered(tmp_path):
    """The one registered middleware is the FRG-NFR-014 listener resource-limit
    middleware (an availability control), and nothing auth-shaped: no CORS, no
    session, no authentication middleware. Auth stays enforced-by-absence
    (FRG-AUTH-001) — the resource limits are keyed by peer address as a DoS
    safety valve, not access control."""
    from foragerr.api.limits import RequestLimitsMiddleware

    app = make_app(tmp_path, "cfg")
    installed = [mw.cls for mw in app.user_middleware]
    assert installed == [RequestLimitsMiddleware]


@pytest.mark.req("FRG-AUTH-001")
def test_no_route_declares_a_dependency(tmp_path):
    """A route-inventory check: no route (and no router-level default) has
    any FastAPI dependency registered — auth is enforced via Depends() in
    this stack, so an empty dependant list means no auth (or anything else)
    gates any route.

    ``iter_route_contexts`` is the same walk FastAPI's own OpenAPI generator
    uses: mounted routers are lazily resolved in this FastAPI version, so
    ``app.routes`` alone does not reach routes nested under ``include_router``.
    """
    app = make_app(tmp_path, "cfg")
    checked = 0
    for ctx in routing.iter_route_contexts(app.routes):
        original = ctx.original_route
        if not isinstance(original, APIRoute):
            continue
        checked += 1
        assert original.dependant.dependencies == [], (
            f"route {ctx.path!r} has a dependency registered"
        )
    assert checked >= 4  # sanity: command(x2)/command/{id}/system-status were checked


@pytest.mark.req("FRG-AUTH-001")
def test_health_and_api_v1_respond_without_any_credentials(tmp_path):
    app = make_app(tmp_path, "cfg")
    with TestClient(app) as client:
        # Explicitly no Authorization header, no cookies, no api-key param.
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/system/status").status_code == 200
        created = client.post("/api/v1/command", json={"name": "noop"})
        assert created.status_code == 201
        assert client.get(f"/api/v1/command/{created.json()['id']}").status_code == 200
        assert client.get("/api/v1/command").status_code == 200


@pytest.mark.req("FRG-AUTH-001")
def test_no_dormant_login_or_session_code_paths_in_backend_src():
    offenders = []
    for path in sorted(SRC_DIR.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _AUTH_SMELL_RE.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "auth-shaped code found in backend/src — M1 is auth-mode 'none' only "
        "(FRG-AUTH-001), nothing latent for M3 to half-enable:\n"
        + "\n".join(offenders)
    )


@pytest.mark.req("FRG-AUTH-001")
def test_no_auth_setting_exists_in_config():
    from foragerr.config import Settings

    assert not any(
        "auth" in name.lower() or "password" in name.lower() or "session" in name.lower()
        for name in Settings.model_fields
    )
