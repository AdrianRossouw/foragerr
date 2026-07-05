"""``POST``/``GET /api/v1/command`` transport over the command backbone
(FRG-API-001), plus the app-factory/OpenAPI-accuracy scenarios of
FRG-API-001 itself."""

from __future__ import annotations

import time

import pytest
from fastapi import routing
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.config import Settings


def make_settings(tmp_path, name: str) -> Settings:
    path = tmp_path / name
    path.mkdir()
    return Settings(config_dir=path)


@pytest.fixture
def client(tmp_path):
    app = create_app(make_settings(tmp_path, "cfg"))
    with TestClient(app) as c:
        yield c


def route_contexts(app):
    """Every effective route on ``app``, prefixes resolved (mounted routers
    are lazily resolved in this FastAPI version — ``app.routes`` alone does
    not flatten them; ``iter_route_contexts`` is the same walk FastAPI's own
    OpenAPI generator uses)."""
    return list(routing.iter_route_contexts(app.routes))


def all_paths(app) -> list[str]:
    return [ctx.path for ctx in route_contexts(app) if ctx.path is not None]


def schema_route_paths(app) -> set[str]:
    return {
        ctx.path
        for ctx in route_contexts(app)
        if ctx.path is not None
        and isinstance(ctx.original_route, APIRoute)
        and ctx.include_in_schema
    }


# -- FRG-API-001: app factory / OpenAPI accuracy -----------------------------


@pytest.mark.req("FRG-API-001")
def test_every_route_is_under_api_v1_except_health(tmp_path):
    app = create_app(make_settings(tmp_path, "prefix"))
    paths = all_paths(app)
    assert paths  # sanity: routes actually exist
    # Sanctioned top-level surfaces outside /api/v1 (design decision 5,
    # m1-ui-opds-deploy): the /health probe and the OPDS catalog listener,
    # mounted at the configured base path (default /opds, FRG-OPDS-001).
    opds_base = app.state.settings.opds_base_path
    for path in paths:
        assert (
            path == "/health"
            or path.startswith("/api/v1")
            or path == opds_base
            or path.startswith(opds_base + "/")
        ), path


@pytest.mark.req("FRG-API-001")
def test_openapi_paths_exactly_cover_the_registered_schema_routes(tmp_path):
    app = create_app(make_settings(tmp_path, "openapi"))
    with TestClient(app) as c:
        openapi = c.get("/api/v1/openapi.json").json()
    documented = set(openapi["paths"])
    schema_routes = schema_route_paths(app)
    assert documented == schema_routes
    assert "/api/v1/command" in documented
    assert "/api/v1/command/{command_id}" in documented
    assert "/api/v1/system/status" in documented
    assert "/health" not in documented  # health is Docker-facing, not UI/OpenAPI


@pytest.mark.req("FRG-API-001")
def test_two_app_instances_are_independent_but_equivalently_routed(tmp_path):
    app_a = create_app(make_settings(tmp_path, "a"))
    app_b = create_app(make_settings(tmp_path, "b"))
    assert app_a is not app_b
    paths_a = sorted(all_paths(app_a))
    paths_b = sorted(all_paths(app_b))
    assert paths_a == paths_b


# -- command transport --------------------------------------------------------


@pytest.mark.req("FRG-API-001")
def test_post_command_returns_201_and_a_command_resource(client):
    response = client.post(
        "/api/v1/command", json={"name": "noop", "payload": {"note": "hello"}}
    )
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], int)
    assert body["name"] == "noop"
    assert body["status"] in ("queued", "started", "completed")


@pytest.mark.req("FRG-API-001")
def test_get_command_by_id_reflects_eventual_completion(client):
    created = client.post(
        "/api/v1/command", json={"name": "noop", "payload": {"note": "round-trip"}}
    ).json()

    def _completed():
        body = client.get(f"/api/v1/command/{created['id']}").json()
        return body if body["status"] == "completed" else None

    deadline = time.monotonic() + 5.0
    body = None
    while time.monotonic() < deadline:
        body = _completed()
        if body:
            break
        time.sleep(0.05)
    assert body is not None, "command never reached 'completed'"
    assert body["result"] == "round-trip"


@pytest.mark.req("FRG-API-001")
def test_get_unknown_command_id_is_404(client):
    response = client.get("/api/v1/command/123456789")
    assert response.status_code == 404


@pytest.mark.req("FRG-API-001")
def test_resubmitting_an_equal_bodied_command_dedups_to_the_same_id(client):
    """Dedup is observable through this transport (FRG-SCHED-003 behavior,
    exercised — not re-tested — here)."""
    payload = {"note": "dedup-me"}
    first = client.post("/api/v1/command", json={"name": "noop", "payload": payload})
    second = client.post("/api/v1/command", json={"name": "noop", "payload": payload})
    assert first.status_code == 201
    assert second.status_code == 201
    # Racy only if the first command finishes before the second POST lands;
    # noop with a fresh unique payload here is fast but not instantaneous,
    # and dedup only applies while queued/started — assert the *typical*
    # observable case: while still eligible, the id matches.
    if first.json()["status"] != "completed":
        assert second.json()["id"] == first.json()["id"]


@pytest.mark.req("FRG-API-001")
def test_post_command_with_a_scheduled_tasks_command_name_is_the_same_transport(client):
    """A scheduled task's underlying command ('housekeeping') can be
    triggered through the same POST transport as any other command —
    demonstrating the force-run surface without re-testing FRG-SCHED-007
    itself (owned by the sched area)."""
    response = client.post("/api/v1/command", json={"name": "housekeeping"})
    assert response.status_code == 201
    assert response.json()["name"] == "housekeeping"


@pytest.mark.req("FRG-API-001")
def test_paged_command_list_is_reachable(client):
    client.post("/api/v1/command", json={"name": "noop", "payload": {"note": "x"}})
    response = client.get("/api/v1/command")
    assert response.status_code == 200
    body = response.json()
    assert body["totalRecords"] >= 1
