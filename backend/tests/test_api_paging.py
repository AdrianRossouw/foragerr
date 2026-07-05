"""Paging-envelope helper: shape, sorting, and whitelist enforcement
(FRG-API-002), demonstrated on ``GET /api/v1/command``."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from foragerr.api.errors import ApiError
from foragerr.api.paging import resolve_sort_order
from foragerr.app import create_app
from foragerr.config import Settings
from foragerr.db import CommandRow


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "cfg"
    path.mkdir()
    app = create_app(Settings(config_dir=path))
    with TestClient(app) as c:
        yield c


def _seed(client, count: int) -> list[int]:
    ids = []
    for i in range(count):
        response = client.post(
            "/api/v1/command", json={"name": "noop", "payload": {"note": f"seed-{i}"}}
        )
        assert response.status_code == 201
        ids.append(response.json()["id"])
    return ids


@pytest.mark.req("FRG-API-002")
def test_paged_list_envelope_shape_and_slicing(client):
    _seed(client, 5)  # plus the startup-registered housekeeping row: >= 6 total
    response = client.get(
        "/api/v1/command", params={"page": 1, "pageSize": 2, "sortKey": "name"}
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "page",
        "pageSize",
        "sortKey",
        "sortDirection",
        "totalRecords",
        "records",
    }
    assert body["page"] == 1
    assert body["pageSize"] == 2
    assert len(body["records"]) == 2
    assert body["totalRecords"] >= 6


@pytest.mark.req("FRG-API-002")
def test_paged_list_is_correctly_sorted(client):
    _seed(client, 3)
    response = client.get(
        "/api/v1/command",
        params={"page": 1, "pageSize": 50, "sortKey": "name", "sortDirection": "asc"},
    )
    names = [r["name"] for r in response.json()["records"]]
    assert names == sorted(names)


@pytest.mark.req("FRG-API-002")
def test_unknown_sort_key_is_400_uniform_shape_not_500(client):
    response = client.get(
        "/api/v1/command", params={"sortKey": "title; DROP TABLE commands--"}
    )
    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"message", "errors"}
    assert body["errors"][0]["field"] == "sortKey"


@pytest.mark.req("FRG-API-002")
def test_unknown_sort_key_does_not_break_the_table(client):
    """The injection payload must never reach an ORDER BY clause: the table
    keeps working for a subsequent, valid request."""
    client.get("/api/v1/command", params={"sortKey": "title; DROP TABLE commands--"})
    response = client.get("/api/v1/command")
    assert response.status_code == 200


@pytest.mark.req("FRG-API-002")
def test_invalid_sort_direction_is_400_uniform_shape(client):
    response = client.get(
        "/api/v1/command", params={"sortKey": "name", "sortDirection": "sideways"}
    )
    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "sortDirection"


@pytest.mark.req("FRG-API-002")
def test_paging_helper_maps_whitelisted_keys_to_fixed_columns_directly():
    """Unit-level check on the reusable helper itself (not just one endpoint):
    a whitelisted key resolves to its column; an unlisted key never reaches
    SQL — it raises before any column expression is built."""
    whitelist = {"queued_at": CommandRow.queued_at, "status": CommandRow.status}
    order = resolve_sort_order("queued_at", "asc", whitelist)
    assert "commands.queued_at" in str(order)

    with pytest.raises(ApiError) as excinfo:
        resolve_sort_order("title; DROP TABLE--", "asc", whitelist)
    assert excinfo.value.status_code == 400
    assert excinfo.value.field == "sortKey"
