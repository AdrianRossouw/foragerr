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


# --- POST add-time book-type override (FRG-SER-005/018) ----------------------


@pytest.mark.req("FRG-SER-018")
@pytest.mark.req("FRG-SER-005")
def test_post_series_explicit_booktype_is_persisted_locked(
    client, tmp_path, monkeypatch
):
    """An explicit book-type override wins over the title cue and locks."""
    root_id = make_root_folder(client, tmp_path)
    # Title cue would derive "gn"; the override "tpb" must win.
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(50, name="Nimona Graphic Novel").handler(),
    )
    patch_comicvine(monkeypatch, factory)

    response = client.post(
        "/api/v1/series",
        json={"cv_volume_id": 50, "root_folder_id": root_id, "booktype": "tpb"},
    )
    assert response.status_code == 201
    assert response.json()["booktype"] == "tpb"


@pytest.mark.req("FRG-SER-018")
@pytest.mark.req("FRG-SER-005")
def test_post_series_explicit_single_issues_persists_null(
    client, tmp_path, monkeypatch
):
    """The literal "none" locks an explicit single-issues (NULL) choice even
    when the title carries a collected-edition cue."""
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(51, name="Saga TPB").handler(),
    )
    patch_comicvine(monkeypatch, factory)

    response = client.post(
        "/api/v1/series",
        json={"cv_volume_id": 51, "root_folder_id": root_id, "booktype": "none"},
    )
    assert response.status_code == 201
    assert response.json()["booktype"] is None


@pytest.mark.req("FRG-SER-018")
@pytest.mark.req("FRG-SER-005")
def test_post_series_explicit_null_booktype_locks_like_none(
    client, tmp_path, monkeypatch
):
    """An explicit JSON ``null`` is an explicit single-issues choice, distinct
    from omitting the field: it must persist NULL (not derive the title's
    collected-edition cue). Presence is read from ``model_fields_set``, so
    ``null`` and the ``"none"`` sentinel behave identically."""
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(54, name="Saga TPB").handler(),
    )
    patch_comicvine(monkeypatch, factory)

    response = client.post(
        "/api/v1/series",
        json={"cv_volume_id": 54, "root_folder_id": root_id, "booktype": None},
    )
    assert response.status_code == 201
    # derivation would have produced "tpb" from the title cue — the explicit
    # null overrode it, proving null was treated as present, not omitted.
    assert response.json()["booktype"] is None


@pytest.mark.req("FRG-SER-018")
@pytest.mark.req("FRG-SER-005")
def test_post_series_without_booktype_derives_from_title(
    client, tmp_path, monkeypatch
):
    """Omitting the field derives from the title cue exactly as before."""
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(52, name="Saga TPB").handler(),
    )
    patch_comicvine(monkeypatch, factory)

    response = client.post(
        "/api/v1/series",
        json={"cv_volume_id": 52, "root_folder_id": root_id},
    )
    assert response.status_code == 201
    assert response.json()["booktype"] == "tpb"


@pytest.mark.req("FRG-SER-018")
def test_post_series_invalid_booktype_is_rejected_and_adds_nothing(
    client, tmp_path, monkeypatch
):
    """An unknown book-type value is rejected at the model boundary and leaves
    no series row behind. The app normalizes request-body validation failures
    to the uniform 400 `{message, errors}` shape (see `api/errors.py`), so a bad
    vocabulary value surfaces there with a clear message — not a bare 422."""
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(53, name="Saga").handler(),
    )
    patch_comicvine(monkeypatch, factory)

    response = client.post(
        "/api/v1/series",
        json={"cv_volume_id": 53, "root_folder_id": root_id, "booktype": "omnibus"},
    )
    assert response.status_code == 400
    assert set(response.json()) == {"message", "errors"}
    assert "booktype" in response.text  # the clear message names the field
    assert client.get("/api/v1/series").json()["totalRecords"] == 0


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


async def _add_issue_with_file(app, series_id: int, path) -> None:
    async with app.state.db.write_session() as session:
        issue = await repo.create_issue(
            session, series_id=series_id, cv_issue_id=9001, issue_number="1"
        )
        await repo.add_issue_file(
            session, issue_id=issue.id, path=str(path), size=path.stat().st_size
        )


@pytest.mark.req("FRG-API-003")
def test_delete_series_with_delete_files_true_enqueues_command_then_removes(
    client, tmp_path, monkeypatch
):
    """`deleteFiles=true` no longer runs inline (gate fix): the per-file recycle
    moves are blocking syscalls that would freeze the loop for a big series on a
    slow mount, and running inline ignored the import exclusivity group. It now
    ENQUEUES a `delete-series-files` command and returns 202 with the
    CommandResource; the command (pp pool, import-file-mutation group) disposes
    of the file BEFORE removing the rows. Bin routing and the
    ordering/compensation guarantees are pinned in
    tests/library/test_flows_edit_delete.py."""
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings, handler=FakeCV().volume(1, name="Saga").handler()
    )
    patch_comicvine(monkeypatch, factory)
    created = client.post(
        "/api/v1/series", json={"cv_volume_id": 1, "root_folder_id": root_id}
    ).json()
    on_disk = Path(created["path"]) / "Saga 001.cbz"
    on_disk.parent.mkdir(parents=True, exist_ok=True)
    on_disk.write_bytes(b"comic-bytes")
    client.portal.call(_add_issue_with_file, client.app, created["id"], on_disk)

    response = client.delete(
        f"/api/v1/series/{created['id']}", params={"deleteFiles": "true"}
    )
    assert response.status_code == 202
    body = response.json()
    assert body["name"] == "delete-series-files"
    command_id = body["id"]

    # The command runs on the pp worker; poll it to a terminal state.
    def _finished() -> bool:
        status = client.get(f"/api/v1/command/{command_id}").json()["status"]
        return status in ("completed", "failed")

    for _ in range(200):
        if _finished():
            break
        time.sleep(0.05)
    final = client.get(f"/api/v1/command/{command_id}").json()
    assert final["status"] == "completed", final
    assert "binned=0" in (final["result"] or "")  # no bin configured here

    assert client.get(f"/api/v1/series/{created['id']}").status_code == 404
    assert not on_disk.exists()  # the file went with the rows


@pytest.mark.req("FRG-API-003")
def test_delete_nonexistent_series_with_delete_files_true_is_404(client):
    """The M1 501-precedence quirk is gone with the implementation: an unknown
    id with `deleteFiles=true` is a plain not-found."""
    response = client.delete(
        "/api/v1/series/999999", params={"deleteFiles": "true"}
    )
    assert response.status_code == 404


# --- lookup ------------------------------------------------------------------
#
# NOTE: FakeCV (flows_support) only answers `get_volume`/`get_issues` (the
# add/refresh-flow endpoints); `/series/lookup` rides `search_series`, which
# hits ComicVine's DIFFERENT `volumes/` (plural, filtered) search endpoint.
# These lookup tests build a tiny self-contained search handler instead of
# reusing FakeCV.


def _cv_search_envelope(
    volumes: list[dict], *, advertised: int | None = None
) -> "httpx.Response":
    import json as _json

    import httpx

    payload = {
        "status_code": 1,
        "results": volumes,
        "number_of_total_results": len(volumes) if advertised is None else advertised,
    }
    return httpx.Response(200, content=_json.dumps(payload).encode())


def _search_handler(
    volumes: list[dict], *, status: int = 200, advertised: int | None = None
):
    """The one ``volumes/`` search scaffold for every lookup test.

    ``status`` != 200 rejects the search outright with that HTTP status (401
    drives the real client's ``ComicVineAuthError`` carve-out in
    ``_paginate``); ``advertised`` overstates ``number_of_total_results`` so
    the real pagination walk finishes with fewer items than advertised and
    marks the result ``complete=False`` (a non-auth degrade, no page raises).
    ``volumes`` is served on the first page only; later offsets are empty.
    """
    import httpx

    def _handle(request: httpx.Request) -> httpx.Response:
        if "/volumes/" not in str(request.url):
            return httpx.Response(404, content=b"unknown endpoint")
        if status != 200:
            return httpx.Response(status, content=b"rejected")
        offset = int(request.url.params.get("offset", "0"))
        return _cv_search_envelope(
            volumes if offset == 0 else [], advertised=advertised
        )

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
    body = response.json()
    assert body["complete"] is True  # complete walk over a matched result set
    assert body["truncated"] is False  # nowhere near the result cap
    candidates = body["records"]
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
    assert response.json()["records"][0]["have_it"] is True


async def _raise_comicvine_unavailable(self, term, **_kwargs):
    from foragerr.metadata import ComicVineUnavailable

    raise ComicVineUnavailable("simulated upstream failure")


async def _raise_budget_exhausted(self, term, **_kwargs):
    from foragerr.metadata import ComicVineBudgetExhausted

    raise ComicVineBudgetExhausted("volumes", retry_after_seconds=600.0)


@pytest.mark.req("FRG-META-016")
def test_lookup_budget_exhausted_surfaces_honest_resume_message(client, monkeypatch):
    """A per-path budget refusal on an interactive lookup surfaces the typed
    error through the existing lookup-error path as a 503 with an honest,
    key-free message that includes the resume time (FRG-META-016)."""
    from foragerr.metadata import ComicVineClient

    monkeypatch.setattr(ComicVineClient, "search_series", _raise_budget_exhausted)

    response = client.get("/api/v1/series/lookup", params={"term": "Saga"})
    assert response.status_code == 503
    message = response.json()["message"].lower()
    assert "budget" in message and "retries in about 10 minute" in message


@pytest.mark.req("FRG-API-003")
def test_lookup_upstream_failure_maps_to_503(client, monkeypatch):
    """Tests the router's OWN error-mapping in isolation from the real
    client's pagination behavior. Per FRG-META-004, ``search_series``
    degrades a NON-auth mid-walk failure to a partial/empty ``complete=False``
    result (so the generic 503 arm is a defensive backstop it can't normally
    reach), while an auth failure DOES raise and is mapped by the dedicated
    auth arm. Patch just the one method on the REAL ComicVineClient class
    rather than reimplementing its whole async-context-manager protocol in a
    stub."""
    from foragerr.metadata import ComicVineClient

    monkeypatch.setattr(ComicVineClient, "search_series", _raise_comicvine_unavailable)

    response = client.get("/api/v1/series/lookup", params={"term": "Saga"})
    assert response.status_code == 503
    assert set(response.json()) == {"message", "errors"}


#: The exact static 503 message a lookup auth failure surfaces (asserted here
#: so the frontend's credential-error sniff has a stable contract to key off).
#: Composed from the ONE shared constant every credential surface uses.
from foragerr.metadata import COMICVINE_CREDENTIAL_MESSAGE

_LOOKUP_AUTH_MESSAGE = f"comicvine lookup failed: {COMICVINE_CREDENTIAL_MESSAGE}"


@pytest.mark.req("FRG-API-003")
def test_lookup_auth_failure_is_503_naming_the_key_without_leaking_it(
    client, monkeypatch, caplog
):
    """A missing/invalid ComicVine key propagates out of the walk (as a real
    401 -> ``ComicVineAuthError``) and maps to a 503 whose message names the
    credential, whose ``errors[]`` entry carries the machine-readable field
    discriminator, and which logs a static warning — never the key value."""
    import logging

    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler([], status=401)
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    with caplog.at_level(logging.WARNING, logger="foragerr.api.series"):
        response = client.get("/api/v1/series/lookup", params={"term": "Saga"})
    assert response.status_code == 503
    body = response.json()
    assert body["message"] == _LOOKUP_AUTH_MESSAGE
    # machine-readable discriminator: clients classify by field, never prose
    assert body["errors"][0]["field"] == "comicvine_api_key"
    # a warning log line names the credential failure...
    assert any(
        "series lookup rejected by ComicVine: API key missing or invalid"
        == record.getMessage()
        for record in caplog.records
    )
    # ...and the key value (flows_settings default) appears in neither the
    # body nor the log
    assert "CV-SECRET-KEY-abc123" not in response.text
    assert "CV-SECRET-KEY-abc123" not in caplog.text


@pytest.mark.req("FRG-API-003")
def test_lookup_degraded_walk_is_200_incomplete_with_partial_records(
    client, monkeypatch
):
    """A non-auth degraded walk returns a 200 envelope flagged incomplete —
    but NOT truncated — alongside the partial candidates it did retrieve."""
    volumes = [{"id": 101, "name": "Saga", "start_year": "2012"}]
    factory = build_factory(
        settings=client.app.state.settings,
        handler=_search_handler(volumes, advertised=10),
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    response = client.get("/api/v1/series/lookup", params={"term": "Saga"})
    assert response.status_code == 200
    body = response.json()
    assert body["complete"] is False
    assert body["truncated"] is False  # a degrade, not a deliberate cap
    assert len(body["records"]) == 1
    assert body["records"][0]["cv_volume_id"] == 101


@pytest.mark.req("FRG-API-003")
def test_lookup_capped_walk_is_200_truncated(tmp_path, monkeypatch):
    """A walk deliberately stopped at the configured search-result cap marks
    the envelope ``truncated=true`` (narrow the term; retry cannot help),
    distinct from the transient ``complete=false`` degrade."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    capped_settings = flows_settings(cfg, comicvine_search_result_cap=1)
    volumes = [
        {"id": 101, "name": "Saga", "start_year": "2012"},
        {"id": 102, "name": "Saga Deluxe", "start_year": "2014"},
    ]
    factory = build_factory(settings=capped_settings, handler=_search_handler(volumes))
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    app = create_app(capped_settings)
    with TestClient(app) as capped_client:
        response = capped_client.get("/api/v1/series/lookup", params={"term": "Saga"})
    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is True
    assert body["complete"] is False  # a capped result set is also incomplete
    assert len(body["records"]) == 1  # cut to the cap


@pytest.mark.req("FRG-META-007")
def test_lookup_reports_hidden_count_and_reveals_flagged_with_include_ignored(
    tmp_path, monkeypatch
):
    """The lookup envelope carries ``hidden_by_ignore_list`` (never a silent
    drop), and ``includeIgnored=true`` returns the hidden volumes flagged
    ``ignored`` so the add screen can recover them (FRG-META-007 / FRG-UI-032)."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    ignore_settings = flows_settings(
        cfg, comicvine_ignored_publishers="Panini*, Reprint House"
    )
    volumes = [
        {"id": 101, "name": "Saga", "start_year": "2012",
         "publisher": {"name": "Image Comics"}},
        {"id": 102, "name": "Saga", "start_year": "2013",
         "publisher": {"name": "Panini Verlag"}},  # wildcard match
        {"id": 103, "name": "Saga", "start_year": "2014",
         "publisher": {"name": "Reprint House"}},  # exact match
    ]
    factory = build_factory(settings=ignore_settings, handler=_search_handler(volumes))
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    app = create_app(ignore_settings)
    with TestClient(app) as ignore_client:
        # Default: hidden volumes excluded but COUNTED.
        default = ignore_client.get(
            "/api/v1/series/lookup", params={"term": "Saga"}
        )
        assert default.status_code == 200
        body = default.json()
        assert body["hidden_by_ignore_list"] == 2
        ids = {r["cv_volume_id"] for r in body["records"]}
        assert ids == {101}  # only the non-ignored volume
        assert all(r["ignored"] is False for r in body["records"])

        # includeIgnored: the hidden volumes come back, flagged.
        revealed = ignore_client.get(
            "/api/v1/series/lookup",
            params={"term": "Saga", "includeIgnored": "true"},
        )
        assert revealed.status_code == 200
        rbody = revealed.json()
        assert rbody["hidden_by_ignore_list"] == 2  # still counted
        by_id = {r["cv_volume_id"]: r for r in rbody["records"]}
        assert set(by_id) == {101, 102, 103}
        assert by_id[101]["ignored"] is False
        assert by_id[102]["ignored"] is True
        assert by_id[103]["ignored"] is True


@pytest.mark.req("FRG-API-003")
def test_lookup_clean_empty_is_200_complete_with_no_records(client, monkeypatch):
    """A complete walk that genuinely matched nothing stays a 200 with
    ``complete=true`` (and ``truncated=false``) and an empty record list —
    distinct from a degrade and from a capped walk."""
    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler([])
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    response = client.get("/api/v1/series/lookup", params={"term": "Saga"})
    assert response.status_code == 200
    body = response.json()
    assert body["complete"] is True
    assert body["truncated"] is False
    assert body["records"] == []


# --- suggest (FRG-API-017) ---------------------------------------------------
#
# `GET /series/lookup/suggest` rides `ComicVineClient.suggest_series` (a
# single-page fetch over the SAME `volumes/` search endpoint `/lookup` uses),
# so `_search_handler` above is reused unchanged. These tests focus on what
# is DIFFERENT from `/lookup`: no `truncated` field, a ~10 cap, and the SAME
# 503/auth mapping reused (not re-implemented) from the lookup route.


@pytest.mark.req("FRG-API-017")
def test_suggest_returns_bounded_candidates_without_walking(client, monkeypatch):
    volumes = [{"id": 101, "name": "Saga", "start_year": "2012"}]
    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler(volumes)
    )
    monkeypatch.setattr("foragerr.api.series.comicvine_factory", lambda _settings: factory)

    response = client.get("/api/v1/series/lookup/suggest", params={"term": "Saga"})
    assert response.status_code == 200
    body = response.json()
    assert body["complete"] is True
    assert set(body) == {"records", "complete"}  # NO `truncated` field
    candidates = body["records"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["cv_volume_id"] == 101
    assert candidate["name"] == "Saga"
    assert candidate["start_year"] == 2012
    assert candidate["have_it"] is False
    # no plausibility annotations (unlike a lookup candidate)
    assert "name_similarity" not in candidate
    assert "year_proximity" not in candidate
    assert "target_issue_plausible" not in candidate

    assert client.get("/api/v1/series").json()["totalRecords"] == 0


@pytest.mark.req("FRG-API-017")
def test_suggest_marks_have_it_true_for_an_existing_series(
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

    response = client.get("/api/v1/series/lookup/suggest", params={"term": "Saga"})
    assert response.json()["records"][0]["have_it"] is True


@pytest.mark.req("FRG-API-017")
def test_suggest_upstream_failure_is_200_complete_false(client, monkeypatch):
    """A single failed page degrades to `complete=false` with no candidates —
    NOT a 503 (that arm is reserved for auth failures, mirroring `/lookup`'s
    per-page-failure behaviour)."""
    factory = build_factory(
        settings=client.app.state.settings,
        handler=_search_handler([], status=500),
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    response = client.get("/api/v1/series/lookup/suggest", params={"term": "Saga"})
    assert response.status_code == 200
    body = response.json()
    assert body["complete"] is False
    assert body["records"] == []


@pytest.mark.req("FRG-API-017")
def test_suggest_auth_failure_is_503_naming_the_key_without_leaking_it(
    client, monkeypatch, caplog
):
    """SAME 503 + `field="comicvine_api_key"` + no-key-leak contract as
    `/lookup` (reused mapping, not a parallel copy) — see
    `_LOOKUP_AUTH_MESSAGE`/`_comicvine_error_to_api_error`."""
    import logging

    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler([], status=401)
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    with caplog.at_level(logging.WARNING, logger="foragerr.api.series"):
        response = client.get(
            "/api/v1/series/lookup/suggest", params={"term": "Saga"}
        )
    assert response.status_code == 503
    body = response.json()
    assert body["message"] == _LOOKUP_AUTH_MESSAGE
    assert body["errors"][0]["field"] == "comicvine_api_key"
    assert any(
        "series lookup rejected by ComicVine: API key missing or invalid"
        == record.getMessage()
        for record in caplog.records
    )
    assert "CV-SECRET-KEY-abc123" not in response.text
    assert "CV-SECRET-KEY-abc123" not in caplog.text


@pytest.mark.req("FRG-API-017")
def test_suggest_caps_at_roughly_ten_candidates(client, monkeypatch):
    volumes = [
        {"id": i, "name": f"Saga {i}", "start_year": "2012"} for i in range(15)
    ]
    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler(volumes)
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    response = client.get("/api/v1/series/lookup/suggest", params={"term": "Saga"})
    assert response.status_code == 200
    assert len(response.json()["records"]) <= 10


@pytest.mark.req("FRG-API-017")
def test_suggest_route_is_not_shadowed_by_series_id_route(client, monkeypatch):
    """`/lookup/suggest` is registered before `/{series_id}` (like `/lookup`)
    so it is reachable at all rather than 422-ing on an int-path mismatch."""
    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler([])
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    response = client.get("/api/v1/series/lookup/suggest", params={"term": "Saga"})
    assert response.status_code == 200


# --- relevance ordering (FRG-META-015) ---------------------------------------


@pytest.mark.req("FRG-META-015")
@pytest.mark.req("FRG-META-007")
def test_lookup_ranks_closest_title_match_first(client, monkeypatch):
    """Candidates arrive from CV in `name:asc` order; the closest matching-key
    match must be returned first, ahead of an alphabetically-earlier but less
    similar candidate."""
    volumes = [
        {"id": 1, "name": "Sabrina", "start_year": "2018"},
        {"id": 2, "name": "Saga", "start_year": "2012"},
        {"id": 3, "name": "Sagas of the Northmen", "start_year": "1998"},
    ]
    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler(volumes)
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    records = client.get(
        "/api/v1/series/lookup", params={"term": "Saga"}
    ).json()["records"]
    assert [r["name"] for r in records][0] == "Saga"
    # The exact-match jumped ahead of the alphabetically-earlier "Sabrina".
    assert records[0]["cv_volume_id"] == 2


@pytest.mark.req("FRG-META-015")
def test_lookup_year_tiebreak_prefers_closer_year(client, monkeypatch):
    """At equal name similarity (two identically-named candidates), the one
    whose start year is closer to the year in the term ranks first — beating
    upstream order."""
    volumes = [
        {"id": 18, "name": "Thor", "start_year": "2018"},
        {"id": 20, "name": "Thor", "start_year": "2020"},
    ]
    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler(volumes)
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    records = client.get(
        "/api/v1/series/lookup", params={"term": "Thor 2020"}
    ).json()["records"]
    assert [r["cv_volume_id"] for r in records] == [20, 18]


@pytest.mark.req("FRG-META-015")
@pytest.mark.req("FRG-META-007")
def test_lookup_ordering_drops_nothing_and_selects_nothing(client, monkeypatch):
    """Ranking is presentation only: every candidate the search produced is
    still present (a very-low-similarity one included) and none is marked
    selected."""
    volumes = [
        {"id": 1, "name": "Saga", "start_year": "2012"},
        {"id": 2, "name": "Completely Unrelated Title", "start_year": "1990"},
        {"id": 3, "name": "Saga of the Swamp Thing", "start_year": "1985"},
    ]
    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler(volumes)
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    records = client.get(
        "/api/v1/series/lookup", params={"term": "Saga"}
    ).json()["records"]
    assert len(records) == 3  # count unchanged, nothing dropped
    assert {r["cv_volume_id"] for r in records} == {1, 2, 3}
    # The low-similarity candidate survives (last, but present).
    assert any(r["cv_volume_id"] == 2 for r in records)
    # There is no auto-selection concept in the payload — no candidate is flagged.
    assert all("selected" not in r for r in records)


@pytest.mark.req("FRG-META-015")
def test_lookup_and_suggest_agree_on_order(client, monkeypatch):
    """The same term through the full lookup and the bounded suggest endpoint
    returns the shared candidates in the same relative order."""
    volumes = [
        {"id": 1, "name": "Sabrina", "start_year": "2018"},
        {"id": 2, "name": "Saga", "start_year": "2012"},
        {"id": 3, "name": "Sagas of the Northmen", "start_year": "1998"},
    ]
    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler(volumes)
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    lookup_order = [
        r["cv_volume_id"]
        for r in client.get(
            "/api/v1/series/lookup", params={"term": "Saga"}
        ).json()["records"]
    ]
    suggest_order = [
        r["cv_volume_id"]
        for r in client.get(
            "/api/v1/series/lookup/suggest", params={"term": "Saga"}
        ).json()["records"]
    ]
    assert lookup_order == suggest_order


@pytest.mark.req("FRG-META-015")
def test_lookup_equal_signal_candidates_keep_upstream_order(client, monkeypatch):
    """Candidates with identical relevance signals (same name, no year in the
    term) fall through to the stable upstream tiebreak and keep CV's order."""
    volumes = [
        {"id": 7, "name": "Nova", "start_year": "2007"},
        {"id": 8, "name": "Nova", "start_year": "2013"},
        {"id": 9, "name": "Nova", "start_year": "1994"},
    ]
    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler(volumes)
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    records = client.get(
        "/api/v1/series/lookup", params={"term": "Nova"}
    ).json()["records"]
    assert [r["cv_volume_id"] for r in records] == [7, 8, 9]


# --- candidate description/deck (FRG-META-007/014) ----------------------------


@pytest.mark.req("FRG-META-014")
@pytest.mark.req("FRG-META-007")
def test_candidate_description_is_sanitized_and_length_bounded(
    client, monkeypatch
):
    """Both candidate resources ship a `description`, but never raw CV HTML:
    tags/script bodies are stripped and the text is truncated to the deck cap
    at a word boundary. Exercised through the REAL client + mapping path, so
    the ingest sanitizer and the API egress cap are both in play."""
    hostile = (
        "<script>alert('xss')</script><p>The <b>sweeping</b> space opera.</p> "
        + "word " * 120  # pushes well past the ~300-char deck cap
    )
    volumes = [{"id": 1, "name": "Saga", "start_year": "2012", "description": hostile}]
    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler(volumes)
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    for path in ("/api/v1/series/lookup", "/api/v1/series/lookup/suggest"):
        candidate = client.get(path, params={"term": "Saga"}).json()["records"][0]
        deck = candidate["description"]
        assert deck is not None
        assert "<" not in deck and ">" not in deck  # no tags survive
        assert "alert" not in deck  # script BODY dropped, not just the tags
        assert deck.startswith("The sweeping space opera.")
        assert len(deck) <= 301  # 300-char cap + the ellipsis
        assert deck.endswith("…")
        # Word-boundary truncation: the cut never splits the repeated token.
        assert deck.rstrip("…").rstrip().endswith("word")


@pytest.mark.req("FRG-META-007")
def test_candidate_without_description_is_null(client, monkeypatch):
    """A CV volume with no description yields `description: null` on both
    endpoints — never an error or a sentinel string."""
    volumes = [{"id": 2, "name": "Nailbiter", "start_year": "2014"}]
    factory = build_factory(
        settings=client.app.state.settings, handler=_search_handler(volumes)
    )
    monkeypatch.setattr(
        "foragerr.api.series.comicvine_factory", lambda _settings: factory
    )

    for path in ("/api/v1/series/lookup", "/api/v1/series/lookup/suggest"):
        response = client.get(path, params={"term": "Nailbiter"})
        assert response.status_code == 200
        candidate = response.json()["records"][0]
        assert "description" in candidate
        assert candidate["description"] is None


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
