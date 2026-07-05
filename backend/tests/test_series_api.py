"""HTTP contract tests for the series router (FRG-API-003, FRG-API-006).

Exercises status codes, response shapes, the paging envelope, sort-key
whitelisting, validation-error mapping, and that POST really enqueues a
trackable command. Flow CORRECTNESS (reconciliation, monitor strategies,
etc.) is already exhaustively covered by ``backend/tests/library/
test_flows_*.py`` — not re-tested here.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flows_support import FakeCV, build_factory, flows_settings
from foragerr.app import create_app
from foragerr.library import repo


# --- fixtures ------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cv_gate():
    """Isolate the process-global ComicVine rate gate around every test in
    this file (mirrors ``backend/tests/library/conftest.py`` and
    ``backend/tests/metadata/cv_support.py`` — this file lives flat under
    ``backend/tests/`` rather than one of those packages, so it doesn't pick
    up either of those autouse fixtures automatically)."""
    from foragerr.metadata import ratelimit

    ratelimit.reset_gate()
    yield
    ratelimit.reset_gate()


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return flows_settings(cfg)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


async def _create_root_folder(app, path: Path) -> int:
    async with app.state.db.write_session() as session:
        row = await repo.create_root_folder(session, str(path))
        return row.id


def make_root_folder(client, tmp_path: Path, name: str = "library-root") -> int:
    root = tmp_path / name
    root.mkdir()
    return client.portal.call(_create_root_folder, client.app, root)


def patch_comicvine(monkeypatch, factory) -> None:
    """Route every ComicVine call site this test drives at the injected
    factory: the API router's own `/series/lookup` seam, the add-flow's
    existence check, and the background refresh-series command handler
    (each module bound its own `comicvine_factory` name via `from ... import`,
    so each call site needs its own patch target)."""
    monkeypatch.setattr("foragerr.api.series.comicvine_factory", lambda _settings: factory)
    monkeypatch.setattr(
        "foragerr.library.flows.add.comicvine_factory", lambda _settings: factory
    )
    monkeypatch.setattr(
        "foragerr.library.flows.refresh.comicvine_factory", lambda _settings: factory
    )


# --- list / detail ---------------------------------------------------------


@pytest.mark.req("FRG-API-003")
@pytest.mark.req("FRG-API-006")
def test_series_list_is_a_paged_envelope_with_statistics(client, tmp_path, monkeypatch):
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(1, name="Saga").volume(2, name="Paper Girls").handler(),
    )
    patch_comicvine(monkeypatch, factory)

    for vid in (1, 2):
        response = client.post(
            "/api/v1/series",
            json={"cv_volume_id": vid, "root_folder_id": root_id},
        )
        assert response.status_code == 201

    response = client.get("/api/v1/series", params={"pageSize": 10})
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
    assert body["totalRecords"] == 2
    assert len(body["records"]) == 2
    for record in body["records"]:
        assert "statistics" in record
        assert set(record["statistics"]) == {
            "issue_count",
            "file_count",
            "missing_count",
            "size_on_disk",
            "next_release_date",
            "last_release_date",
        }


@pytest.mark.req("FRG-API-006")
def test_series_list_unknown_sort_key_is_400(client):
    response = client.get(
        "/api/v1/series", params={"sortKey": "title; DROP TABLE series--"}
    )
    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"message", "errors"}
    assert body["errors"][0]["field"] == "sortKey"


@pytest.mark.req("FRG-API-003")
def test_get_unknown_series_is_404(client):
    response = client.get("/api/v1/series/999999")
    assert response.status_code == 404


# --- POST --------------------------------------------------------------------


@pytest.mark.req("FRG-API-003")
def test_post_series_returns_201_series_plus_refresh_command_id(
    client, tmp_path, monkeypatch
):
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(42, name="Saga", publisher="Image", start_year=2012).handler(),
    )
    patch_comicvine(monkeypatch, factory)

    response = client.post(
        "/api/v1/series",
        json={"cv_volume_id": 42, "root_folder_id": root_id},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["cv_volume_id"] == 42
    assert body["title"] == "Saga"
    assert isinstance(body["refresh_command_id"], int)

    # The command is real and observable through the command transport.
    command = client.get(f"/api/v1/command/{body['refresh_command_id']}")
    assert command.status_code == 200
    assert command.json()["name"] == "refresh-series"


@pytest.mark.req("FRG-API-003")
def test_post_series_with_unregistered_root_folder_is_400(client, monkeypatch):
    factory = build_factory(
        settings=client.app.state.settings, handler=FakeCV().volume(1).handler()
    )
    patch_comicvine(monkeypatch, factory)

    response = client.post(
        "/api/v1/series", json={"cv_volume_id": 1, "root_folder_id": 999999}
    )
    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"message", "errors"}


@pytest.mark.req("FRG-API-003")
def test_post_series_with_nonexistent_cv_volume_is_400(client, tmp_path, monkeypatch):
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings, handler=FakeCV().handler()  # no volume
    )
    patch_comicvine(monkeypatch, factory)

    response = client.post(
        "/api/v1/series", json={"cv_volume_id": 404, "root_folder_id": root_id}
    )
    assert response.status_code == 400


@pytest.mark.req("FRG-API-003")
def test_post_series_full_add_chain_reaches_refresh_completion(
    client, tmp_path, monkeypatch
):
    """End-to-end: POST enqueues a real command on a real worker; polling the
    command id tracks it to a terminal status (proves the queued id is
    genuinely trackable, not just echoed)."""
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(7, name="Saga").issues(7, []).handler(),
    )
    patch_comicvine(monkeypatch, factory)

    response = client.post(
        "/api/v1/series", json={"cv_volume_id": 7, "root_folder_id": root_id}
    )
    assert response.status_code == 201
    command_id = response.json()["refresh_command_id"]

    deadline = time.monotonic() + 5.0
    body = None
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/command/{command_id}").json()
        if body["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert body is not None and body["status"] == "completed"


# --- PUT -----------------------------------------------------------------


@pytest.mark.req("FRG-API-003")
def test_put_series_edits_only_supplied_fields(client, tmp_path, monkeypatch):
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings, handler=FakeCV().volume(1, name="Saga").handler()
    )
    patch_comicvine(monkeypatch, factory)
    created = client.post(
        "/api/v1/series", json={"cv_volume_id": 1, "root_folder_id": root_id}
    ).json()

    response = client.put(f"/api/v1/series/{created['id']}", json={"monitored": False})
    assert response.status_code == 200
    body = response.json()
    assert body["monitored"] is False
    assert body["title"] == "Saga"  # untouched


@pytest.mark.req("FRG-API-003")
def test_put_unknown_series_is_404(client):
    response = client.put("/api/v1/series/999999", json={"monitored": False})
    assert response.status_code == 404


@pytest.mark.req("FRG-API-003")
def test_put_series_invalid_path_is_400(client, tmp_path, monkeypatch):
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings, handler=FakeCV().volume(1, name="Saga").handler()
    )
    patch_comicvine(monkeypatch, factory)
    created = client.post(
        "/api/v1/series", json={"cv_volume_id": 1, "root_folder_id": root_id}
    ).json()

    response = client.put(
        f"/api/v1/series/{created['id']}",
        json={"path": str(tmp_path / "outside-any-root")},
    )
    assert response.status_code == 400


# --- DELETE ----------------------------------------------------------------


@pytest.mark.req("FRG-API-003")
def test_delete_series_removes_row_only(client, tmp_path, monkeypatch):
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings, handler=FakeCV().volume(1, name="Saga").handler()
    )
    patch_comicvine(monkeypatch, factory)
    created = client.post(
        "/api/v1/series", json={"cv_volume_id": 1, "root_folder_id": root_id}
    ).json()

    response = client.delete(f"/api/v1/series/{created['id']}")
    assert response.status_code == 204
    assert client.get(f"/api/v1/series/{created['id']}").status_code == 404


@pytest.mark.req("FRG-API-003")
def test_delete_series_with_delete_files_true_is_501(client, tmp_path, monkeypatch):
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings, handler=FakeCV().volume(1, name="Saga").handler()
    )
    patch_comicvine(monkeypatch, factory)
    created = client.post(
        "/api/v1/series", json={"cv_volume_id": 1, "root_folder_id": root_id}
    ).json()

    response = client.delete(
        f"/api/v1/series/{created['id']}", params={"deleteFiles": "true"}
    )
    assert response.status_code == 501
    # row untouched by the rejected request
    assert client.get(f"/api/v1/series/{created['id']}").status_code == 200


@pytest.mark.req("FRG-API-003")
def test_delete_nonexistent_series_with_delete_files_true_is_still_501(client):
    """Documents a deliberate precedence: `delete_series` (edit_delete.py)
    raises `DeleteFilesNotSupportedError` BEFORE it ever looks the series up
    — the flag is checked first, unconditionally. So `deleteFiles=true`
    against an id that doesn't exist yields 501, not 404: the "not
    implemented" rejection always wins over a not-found check for this
    flag, by the (frozen) flows layer's own contract."""
    response = client.delete(
        "/api/v1/series/999999", params={"deleteFiles": "true"}
    )
    assert response.status_code == 501


# --- lookup ------------------------------------------------------------------
#
# NOTE: FakeCV (flows_support) only answers `get_volume`/`get_issues` (the
# add/refresh-flow endpoints); `/series/lookup` rides `search_series`, which
# hits ComicVine's DIFFERENT `volumes/` (plural, filtered) search endpoint.
# These lookup tests build a tiny self-contained search handler instead of
# reusing FakeCV.


def _cv_search_envelope(volumes: list[dict]) -> "httpx.Response":
    import json as _json

    import httpx

    payload = {
        "status_code": 1,
        "results": volumes,
        "number_of_total_results": len(volumes),
    }
    return httpx.Response(200, content=_json.dumps(payload).encode())


def _search_handler(volumes: list[dict]):
    import httpx

    def _handle(request: httpx.Request) -> httpx.Response:
        if "/volumes/" in str(request.url):
            return _cv_search_envelope(volumes)
        return httpx.Response(404, content=b"unknown endpoint")

    return _handle


@pytest.mark.req("FRG-API-003")
def test_lookup_returns_candidates_without_persisting(client, monkeypatch):
    volumes = [{"id": 101, "name": "Saga", "start_year": "2012"}]
    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler(volumes)
    )
    monkeypatch.setattr("foragerr.api.series.comicvine_factory", lambda _settings: factory)

    response = client.get("/api/v1/series/lookup", params={"term": "Saga"})
    assert response.status_code == 200
    candidates = response.json()
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["cv_volume_id"] == 101
    assert candidate["name"] == "Saga"
    assert candidate["start_year"] == 2012
    assert "name_similarity" in candidate
    assert candidate["have_it"] is False

    assert client.get("/api/v1/series").json()["totalRecords"] == 0


@pytest.mark.req("FRG-API-003")
def test_lookup_marks_have_it_true_for_an_existing_series(
    client, tmp_path, monkeypatch
):
    root_id = make_root_folder(client, tmp_path)
    add_factory = build_factory(
        settings=client.app.state.settings, handler=FakeCV().volume(101, name="Saga").handler()
    )
    patch_comicvine(monkeypatch, add_factory)
    created = client.post(
        "/api/v1/series", json={"cv_volume_id": 101, "root_folder_id": root_id}
    )
    assert created.status_code == 201

    volumes = [{"id": 101, "name": "Saga", "start_year": "2012"}]
    search_factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler(volumes)
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: search_factory
    )

    response = client.get("/api/v1/series/lookup", params={"term": "Saga"})
    assert response.json()[0]["have_it"] is True


async def _raise_comicvine_unavailable(self, term, **_kwargs):
    from foragerr.metadata import ComicVineUnavailable

    raise ComicVineUnavailable("simulated upstream failure")


@pytest.mark.req("FRG-API-003")
def test_lookup_upstream_failure_maps_to_503(client, monkeypatch):
    """Tests the router's OWN error-mapping in isolation from the real
    client's partial-pagination-swallows-errors behavior (search_series
    never raises on a mid-walk transport failure by design — it degrades to
    a partial/empty result instead, per FRG-META-004): patch just the one
    method on the REAL ComicVineClient class rather than reimplementing its
    whole async-context-manager protocol in a stub."""
    from foragerr.metadata import ComicVineClient

    monkeypatch.setattr(ComicVineClient, "search_series", _raise_comicvine_unavailable)

    response = client.get("/api/v1/series/lookup", params={"term": "Saga"})
    assert response.status_code == 503
    assert set(response.json()) == {"message", "errors"}


# --- cover -------------------------------------------------------------------


@pytest.mark.req("FRG-META-013")
def test_cover_endpoint_404_when_absent(client):
    response = client.get("/api/v1/series/123/cover")
    assert response.status_code == 404


@pytest.mark.req("FRG-META-013")
def test_cover_endpoint_serves_cached_file(client):
    covers_dir = Path(client.app.state.settings.config_dir) / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)
    (covers_dir / "55.jpg").write_bytes(b"\xff\xd8\xff\xe0JPEGBYTES")

    response = client.get("/api/v1/series/55/cover")
    assert response.status_code == 200
    assert response.content == b"\xff\xd8\xff\xe0JPEGBYTES"
