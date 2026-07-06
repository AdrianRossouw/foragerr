"""Uniform 4xx error shape for every response, including validation failures
(FRG-API-002)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.config import Settings


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "cfg"
    path.mkdir()
    app = create_app(Settings(config_dir=path))
    with TestClient(app) as c:
        yield c


def _assert_uniform_shape(body: dict) -> None:
    assert set(body) == {"message", "errors"}
    assert isinstance(body["message"], str)
    assert isinstance(body["errors"], list)
    assert "detail" not in body


@pytest.mark.req("FRG-API-002")
def test_pydantic_validation_failure_is_uniform_and_names_the_field(client):
    # priority must be an int; sending a string triggers a real Pydantic
    # request-validation failure (not an application-raised error).
    response = client.post(
        "/api/v1/command", json={"name": "noop", "priority": "not-an-int"}
    )
    assert response.status_code == 400
    body = response.json()
    _assert_uniform_shape(body)
    assert any(err["field"] == "priority" for err in body["errors"])


@pytest.mark.req("FRG-API-002")
def test_get_nonexistent_id_is_404_uniform_shape(client):
    response = client.get("/api/v1/command/999999999")
    assert response.status_code == 404
    _assert_uniform_shape(response.json())


@pytest.mark.req("FRG-API-002")
def test_unknown_route_404_is_uniform_shape_not_starlette_default(client):
    """Even Starlette's own route-not-found path never leaks {"detail": ...}."""
    response = client.get("/api/v1/this-route-does-not-exist")
    assert response.status_code == 404
    _assert_uniform_shape(response.json())


@pytest.mark.req("FRG-API-002")
def test_malformed_json_body_is_uniform_shape(client):
    response = client.post(
        "/api/v1/command",
        content=b"{not valid json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    _assert_uniform_shape(response.json())


@pytest.mark.req("FRG-API-002")
def test_unknown_command_name_is_400_uniform_shape_naming_name_field(client):
    """CommandValidationError (application-raised, not Pydantic-request-level)
    is also mapped into the uniform shape."""
    response = client.post("/api/v1/command", json={"name": "does-not-exist"})
    assert response.status_code == 400
    body = response.json()
    _assert_uniform_shape(body)
    assert body["errors"][0]["field"] == "name"
