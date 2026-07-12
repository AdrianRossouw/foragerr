"""Default-deny perimeter: uniform coverage of every surface (FRG-AUTH-010).

Three-way proof of the invariant:
(a) by construction — the root dependency covers a newly mounted router;
(b) by an exhaustive route-inventory walk over the live route table;
(c) per-surface designated-credential checks (cookie / X-Api-Key / OPDS Basic),
    the query-param API key rejection, and the OPDS Basic realm challenge.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi import routing
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient

from conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USER, TEST_API_KEY
from foragerr.app import create_app
from foragerr.auth.perimeter import EXEMPT_PATHS
from foragerr.config import Settings


def make_app(tmp_path: Path, name: str = "cfg"):
    path = tmp_path / name
    path.mkdir()
    return create_app(Settings(config_dir=path))


def _concrete(path: str) -> str:
    """Fill path params with a dummy value (auth runs before the handler, so the
    concrete value never matters — a bare request is refused first)."""
    out = []
    for segment in path.split("/"):
        out.append("1" if segment.startswith("{") else segment)
    return "/".join(out)


@pytest.mark.req("FRG-AUTH-010")
def test_route_inventory_every_route_is_exempt_or_refuses_bare(tmp_path):
    """Walk every registered route; each is either on the fixed exempt list or
    refuses a bare (credential-free) request with 401/403."""
    app = make_app(tmp_path)
    checked = 0
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)  # send bare requests
        for ctx in routing.iter_route_contexts(app.routes):
            route = ctx.original_route
            path = ctx.path
            if path is None:
                continue
            if isinstance(route, APIWebSocketRoute):
                # WebSocket refusal is covered in test_auth_csrf_ws.py.
                continue
            if not isinstance(route, APIRoute):
                continue
            if path in EXEMPT_PATHS:
                continue
            method = next(iter(route.methods - {"HEAD", "OPTIONS"}), "GET")
            response = client.request(method, _concrete(path))
            checked += 1
            assert response.status_code in (401, 403), (
                f"{method} {path} answered {response.status_code} bare — neither "
                "exempt nor refused (FRG-AUTH-010 breach)"
            )
    assert checked > 20  # sanity: the whole API surface was actually exercised


@pytest.mark.req("FRG-AUTH-010")
def test_exempt_list_is_exactly_health_and_login(tmp_path):
    """The exempt list is pinned to exactly the health probe + login route; the
    health + login endpoints answer without credentials, nothing else does."""
    assert EXEMPT_PATHS == {"/health", "/api/v1/auth/login"}
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        assert client.get("/health").status_code == 200
        # login is reachable bare (it is the one door); a bad body is a 4xx from
        # the handler, never a perimeter 401.
        assert client.post(
            "/api/v1/auth/login", json={"username": "x", "password": "y"}
        ).status_code == 401  # wrong creds, but the route itself was reached


@pytest.mark.req("FRG-AUTH-010")
def test_no_unexpected_mount_serves_bytes_outside_the_perimeter(tmp_path):
    """App-level dependencies never run for a Starlette ``Mount``, so the
    route-inventory walk (which only covers APIRoute/APIWebSocketRoute) cannot
    see one. Pin the invariant the perimeter actually rests on: the ONLY mount
    is the SPA static shell (serves inert UI bytes). A future change that mounts
    sensitive bytes (covers, the download dir, a sub-app) trips this instead of
    silently shipping an unauthenticated surface."""
    from starlette.routing import Mount

    app = make_app(tmp_path)
    mounts = [r for r in app.routes if isinstance(r, Mount)]
    assert all(getattr(m, "name", None) == "spa" for m in mounts), (
        "an unexpected Mount is present — app-level auth does not cover Mounts, "
        "so serving bytes through one bypasses the FRG-AUTH-010 perimeter; route "
        f"it through an APIRoute/OPDS instead. Mounts: {[m.name for m in mounts]}"
    )


@pytest.mark.req("FRG-AUTH-010")
def test_newly_mounted_router_is_covered_by_construction(tmp_path):
    """A router mounted onto the factory app with NO auth annotation still
    refuses bare requests — the perimeter covers additions by construction."""
    app = make_app(tmp_path)
    probe = APIRouter()

    @probe.get("/api/v1/probe-uncovered")
    async def _probe() -> dict:
        return {"ok": True}

    app.include_router(probe)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        assert client.get("/api/v1/probe-uncovered").status_code == 401
        # and with the key it is reachable (proving the route exists + works)
        assert client.get(
            "/api/v1/probe-uncovered", headers={"X-Api-Key": TEST_API_KEY}
        ).status_code == 200


@pytest.mark.req("FRG-AUTH-010")
def test_designated_credentials_per_surface(tmp_path):
    """Each surface succeeds with its designated credential and is refused
    without one; the API key works via header, OPDS via Basic."""
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        # API: X-Api-Key header
        assert client.get("/api/v1/system/status").status_code == 401
        assert client.get(
            "/api/v1/system/status", headers={"X-Api-Key": TEST_API_KEY}
        ).status_code == 200
        # API: session cookie
        login = client.post(
            "/api/v1/auth/login",
            json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD},
        )
        assert login.status_code == 200
        assert client.get("/api/v1/system/status").status_code == 200  # cookie in jar


@pytest.mark.req("FRG-AUTH-010")
def test_api_key_as_query_param_is_not_accepted(tmp_path):
    """An API key presented as a query parameter never authenticates (header
    only) — the query-param key path Mylar exposed does not exist here."""
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        assert client.get(
            f"/api/v1/system/status?apikey={TEST_API_KEY}"
        ).status_code == 401
        assert client.get(
            f"/api/v1/system/status?api_key={TEST_API_KEY}"
        ).status_code == 401
        assert client.get(
            f"/api/v1/system/status?X-Api-Key={TEST_API_KEY}"
        ).status_code == 401


@pytest.mark.req("FRG-AUTH-010")
def test_opds_basic_realm_challenge_and_verification(tmp_path):
    """A bare OPDS request is refused 401 with the Basic realm challenge; the
    correct OPDS password authenticates, a wrong one does not."""
    app = make_app(tmp_path)
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        bare = client.get("/opds")
        assert bare.status_code == 401
        assert bare.headers.get("www-authenticate") == 'Basic realm="foragerr-opds"'

        def basic(user: str, password: str) -> dict:
            token = base64.b64encode(f"{user}:{password}".encode()).decode()
            return {"Authorization": f"Basic {token}"}

        # OPDS password seeds equal to the admin password (no FORAGERR_OPDS_PASSWORD).
        assert client.get(
            "/opds", headers=basic(TEST_ADMIN_USER, TEST_ADMIN_PASSWORD)
        ).status_code == 200
        wrong = client.get("/opds", headers=basic(TEST_ADMIN_USER, "not-the-password"))
        assert wrong.status_code == 401
        assert wrong.headers.get("www-authenticate") == 'Basic realm="foragerr-opds"'
        # The username binds to the principal — a correct password under a
        # wrong username is refused identically (manual authentication.md).
        wrong_user = client.get(
            "/opds", headers=basic("not-the-admin", TEST_ADMIN_PASSWORD)
        )
        assert wrong_user.status_code == 401
        assert (
            wrong_user.headers.get("www-authenticate")
            == 'Basic realm="foragerr-opds"'
        )
