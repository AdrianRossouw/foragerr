"""On-demand CBR→CBZ conversion endpoints (FRG-PP-018).

``POST /api/v1/convert/series`` and ``POST /api/v1/convert/issue`` each enqueue
the file-mutating ``convert-series`` / ``convert-issue`` command onto the
backbone — the same pp-pool, exclusivity-guarded transport ``POST /api/v1/rename``
uses. These assert the route surface + payload mapping (the conversion mechanics
themselves are covered in ``tests/importer/test_convert_cbr.py``)."""

from __future__ import annotations

import pytest
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


@pytest.mark.req("FRG-PP-018")
def test_convert_series_endpoint_enqueues_command(client):
    response = client.post("/api/v1/convert/series", json={"seriesId": 7})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "convert-series"
    assert body["payload"] == {"series_id": 7}
    assert body["workload_class"] == "pp"
    assert body["exclusivity_group"] == "import-file-mutation"


@pytest.mark.req("FRG-PP-018")
def test_convert_issue_endpoint_enqueues_command(client):
    response = client.post("/api/v1/convert/issue", json={"issueId": 42})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "convert-issue"
    assert body["payload"] == {"issue_id": 42}
    assert body["workload_class"] == "pp"
    assert body["exclusivity_group"] == "import-file-mutation"
