"""Series-lookup candidates carry the ComicVine issue count (FRG-META-007).

The add-series screen surfaces how many issues a candidate volume has, so the
``/api/v1/series/lookup`` candidate resource must expose ``count_of_issues``
(mapped from the ComicVine volume's advertised count). This exercises only that
one field; the rest of the lookup contract lives in ``test_series_api.py``.
"""

from __future__ import annotations

import json as _json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from flows_support import build_factory, flows_settings
from foragerr.app import create_app


@pytest.fixture(autouse=True)
def _reset_cv_gate():
    from foragerr.metadata import ratelimit

    ratelimit.reset_gate()
    yield
    ratelimit.reset_gate()


@pytest.fixture
def client(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(flows_settings(cfg))
    with TestClient(app) as c:
        yield c


def _search_handler(volumes: list[dict]):
    def _handle(request: httpx.Request) -> httpx.Response:
        if "/volumes/" in str(request.url):
            payload = {
                "status_code": 1,
                "results": volumes,
                "number_of_total_results": len(volumes),
            }
            return httpx.Response(200, content=_json.dumps(payload).encode())
        return httpx.Response(404, content=b"unknown endpoint")

    return _handle


@pytest.mark.req("FRG-META-007")
def test_lookup_candidate_exposes_count_of_issues(client, monkeypatch):
    volumes = [
        {"id": 101, "name": "Saga", "start_year": "2012", "count_of_issues": 66}
    ]
    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler(volumes)
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    resp = client.get("/api/v1/series/lookup", params={"term": "Saga"})
    assert resp.status_code == 200
    candidate = resp.json()["records"][0]
    assert candidate["count_of_issues"] == 66


@pytest.mark.req("FRG-META-007")
def test_lookup_count_of_issues_is_null_when_comicvine_omits_it(client, monkeypatch):
    volumes = [{"id": 202, "name": "Paper Girls", "start_year": "2015"}]
    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler(volumes)
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    resp = client.get("/api/v1/series/lookup", params={"term": "Paper Girls"})
    assert resp.json()["records"][0]["count_of_issues"] is None
