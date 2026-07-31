"""FRG-DL-008 / FRG-API-007 — queue endpoint built from tracked downloads only."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.config import Settings
from foragerr.downloads.state import TrackedDownloadState
from tracking_support import blocklist_rows, insert_grab_history, insert_tracked, seed_library


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return Settings(config_dir=cfg)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


async def _seed_download(app, tmp_path, state, download_id="q1"):
    series_id, issue_id = await seed_library(app.state.db, tmp_path)
    await insert_grab_history(
        app.state.db, download_id=download_id, series_id=series_id, issue_id=issue_id, guid="G1"
    )
    await insert_tracked(
        app.state.db,
        download_id=download_id,
        state=state,
        series_id=series_id,
        issue_id=issue_id,
        client_name="SAB",
        indexer_name="DogNZB",
    )
    return series_id, issue_id


@pytest.mark.req("FRG-API-007")
@pytest.mark.req("FRG-DL-008")
def test_queue_paged_envelope_from_tracked_downloads(client, tmp_path):
    series_id, issue_id = client.portal.call(
        _seed_download, client.app, tmp_path, TrackedDownloadState.DOWNLOADING
    )
    body = client.get("/api/v1/queue").json()
    # Standard paging envelope (FRG-API-002 shape).
    assert {"page", "pageSize", "sortKey", "sortDirection", "totalRecords", "records"} <= body.keys()
    assert body["totalRecords"] == 1
    rec = body["records"][0]
    assert rec["seriesId"] == series_id and rec["issueId"] == issue_id
    assert rec["series"]["title"] == "Spawn"
    assert rec["issue"]["id"] == issue_id
    assert rec["state"] == TrackedDownloadState.DOWNLOADING.value
    assert rec["downloadId"] == "q1" and rec["downloadClient"] == "SAB"
    assert rec["indexer"] == "DogNZB"
    assert rec["estimatedCompletion"] is not None  # eta present while downloading


@pytest.mark.req("FRG-API-007")
def test_queue_never_calls_a_client_and_needs_none_configured(client, tmp_path):
    # No download client is configured at all; the queue still serves purely from
    # tracked_downloads, proving it makes no live client call at request time.
    client.portal.call(
        _seed_download, client.app, tmp_path, TrackedDownloadState.IMPORT_PENDING
    )
    body = client.get("/api/v1/queue").json()
    assert body["totalRecords"] == 1
    # import_pending stays visible with its state (does not vanish on completion).
    assert body["records"][0]["state"] == TrackedDownloadState.IMPORT_PENDING.value


@pytest.mark.req("FRG-DL-008")
def test_delete_removes_and_blocklists(client, tmp_path):
    client.portal.call(
        _seed_download, client.app, tmp_path, TrackedDownloadState.DOWNLOADING
    )
    queue_id = client.get("/api/v1/queue").json()["records"][0]["id"]

    resp = client.delete(f"/api/v1/queue/{queue_id}?blocklist=true&deleteData=false")
    assert resp.status_code == 200
    assert resp.json()["blocklisted"] is True

    # Gone from the queue, and a blocklist row was written.
    assert client.get("/api/v1/queue").json()["totalRecords"] == 0
    blocks = client.portal.call(blocklist_rows, client.app.state.db)
    assert len(blocks) == 1 and blocks[0].guid == "G1"


@pytest.mark.req("FRG-DL-008")
def test_delete_missing_item_is_404(client):
    assert client.delete("/api/v1/queue/999").status_code == 404


@pytest.mark.req("FRG-DL-010")
def test_delete_refuses_while_importing(client, tmp_path):
    # An in-flight import (state=importing) is actively moving this item's files.
    # A manual remove that deletes client data now would yank files out from
    # under the drain — so it must be refused, and the row left in place.
    client.portal.call(
        _seed_download, client.app, tmp_path, TrackedDownloadState.IMPORTING
    )
    queue_id = client.get("/api/v1/queue").json()["records"][0]["id"]

    resp = client.delete(f"/api/v1/queue/{queue_id}?deleteData=true")

    assert resp.status_code == 409  # import in progress
    # The item is still tracked (not de-tracked out from under the drain).
    body = client.get("/api/v1/queue").json()
    assert body["totalRecords"] == 1
    assert body["records"][0]["state"] == TrackedDownloadState.IMPORTING.value


async def _seed_batch(app, tmp_path, states) -> None:
    """One library plus one tracked download per state, ``b0``..``bN``."""
    series_id, issue_id = await seed_library(app.state.db, tmp_path)
    for index, state in enumerate(states):
        download_id = f"b{index}"
        await insert_grab_history(
            app.state.db,
            download_id=download_id,
            series_id=series_id,
            issue_id=issue_id,
            guid=f"G{index}",
        )
        await insert_tracked(
            app.state.db,
            download_id=download_id,
            state=state,
            series_id=series_id,
            issue_id=issue_id,
        )


def _queue_ids_by_download(client) -> dict[str, int]:
    return {r["downloadId"]: r["id"] for r in client.get("/api/v1/queue").json()["records"]}


@pytest.mark.req("FRG-DL-008")
def test_bulk_remove_applies_per_row_and_refuses_only_the_importing_row(client, tmp_path):
    client.portal.call(
        _seed_batch,
        client.app,
        tmp_path,
        [
            TrackedDownloadState.DOWNLOADING,
            TrackedDownloadState.IMPORTING,
            TrackedDownloadState.FAILED,
        ],
    )
    ids = _queue_ids_by_download(client)

    resp = client.post(
        "/api/v1/queue/remove",
        json={"ids": [ids["b0"], ids["b1"], ids["b2"]], "blocklist": False},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] == 2
    # JSON object keys are strings; the refusal is reported under its own id.
    assert list(body["errors"]) == [str(ids["b1"])]
    assert "import in progress" in body["errors"][str(ids["b1"])]
    # The importing row is still tracked; the other two are gone.
    remaining = _queue_ids_by_download(client)
    assert list(remaining) == ["b1"]


@pytest.mark.req("FRG-DL-008")
def test_bulk_remove_writes_a_blocklist_row_per_removed_release(client, tmp_path):
    client.portal.call(
        _seed_batch,
        client.app,
        tmp_path,
        [TrackedDownloadState.FAILED, TrackedDownloadState.FAILED],
    )
    ids = _queue_ids_by_download(client)

    resp = client.post(
        "/api/v1/queue/remove",
        json={"ids": list(ids.values()), "blocklist": True},
    )

    assert resp.json()["applied"] == 2
    blocks = client.portal.call(blocklist_rows, client.app.state.db)
    # The shared multi-field key, one row per removed release.
    assert sorted(b.guid for b in blocks) == ["G0", "G1"]


@pytest.mark.req("FRG-DL-008")
def test_bulk_remove_reports_an_unknown_id_without_losing_the_batch(client, tmp_path):
    client.portal.call(_seed_batch, client.app, tmp_path, [TrackedDownloadState.FAILED])
    queue_id = _queue_ids_by_download(client)["b0"]

    body = client.post("/api/v1/queue/remove", json={"ids": [queue_id, 999]}).json()

    assert body["applied"] == 1
    assert "not found" in body["errors"]["999"]
    assert client.get("/api/v1/queue").json()["totalRecords"] == 0


@pytest.mark.req("FRG-DL-008")
def test_bulk_remove_de_tracks_even_when_the_client_call_fails(
    client, tmp_path, monkeypatch
):
    # An unreachable download client must never strand a row in the queue: the
    # de-tracking already committed, so the failure is logged, not reported.
    client.portal.call(_seed_batch, client.app, tmp_path, [TrackedDownloadState.FAILED])
    queue_id = _queue_ids_by_download(client)["b0"]

    async def _unreachable(*args, **kwargs):
        raise ConnectionError("download client unreachable")

    monkeypatch.setattr("foragerr.api.queue.build_client_for_id", _unreachable)

    body = client.post(
        "/api/v1/queue/remove", json={"ids": [queue_id], "deleteData": True}
    ).json()

    assert body["applied"] == 1 and body["errors"] == {}
    assert client.get("/api/v1/queue").json()["totalRecords"] == 0


@pytest.mark.req("FRG-DL-008")
def test_bulk_remove_rejects_an_empty_selection(client):
    # Nothing named is a malformed request, not a silent success.
    assert client.post("/api/v1/queue/remove", json={"ids": []}).status_code == 400


@pytest.mark.req("FRG-UI-037")
def test_completed_unimported_download_is_visible_as_awaiting_import(client, tmp_path):
    """A download the client reports complete but foragerr has not yet imported
    is tracked as ``import_pending`` — it must stay in the queue payload with
    that awaiting-import state, never vanish mid-pipeline (F19)."""
    client.portal.call(
        _seed_download,
        client.app,
        tmp_path,
        TrackedDownloadState.IMPORT_PENDING,
        "await-1",
    )
    body = client.get("/api/v1/queue").json()
    assert body["totalRecords"] == 1
    rec = body["records"][0]
    assert rec["state"] == TrackedDownloadState.IMPORT_PENDING.value
    assert rec["downloadId"] == "await-1"
