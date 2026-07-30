"""HTTP contract for the read-only reference library (FRG-SER-021/022).

Registration validates readability instead of writability, the series resource
carries ``read_only`` so the UI can mark it and suppress what the backend would
refuse (FRG-UI-045), and every write/acquire route answers a uniform 409 naming
the reason — never a silent no-op, and never a queued command that fails later
in a worker.

The read-only flag is flipped on a normally seeded root: these tests are about
what the API refuses, not about mount permissions (the one exception is the
registration test, which needs a genuinely unwritable directory).
"""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from foragerr.app import create_app
from foragerr.db import CommandRow
from foragerr.downloads.models import GrabHistoryRow
from foragerr.library.models import IssueRow, RootFolderRow
from opds_support import opds_settings, seed, simple_series


@pytest.fixture
def client(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(opds_settings(cfg))
    with TestClient(app) as c:
        yield c


async def _mark_root_read_only(app, root_id: int) -> None:
    async with app.state.db.write_session() as session:
        row = await session.get(RootFolderRow, root_id)
        row.read_only = True


async def _issue_monitored(app, issue_id: int) -> bool:
    async with app.state.db.read_session() as session:
        return (await session.get(IssueRow, issue_id)).monitored


async def _command_names(app) -> list[str]:
    async with app.state.db.read_session() as session:
        return list((await session.execute(select(CommandRow.name))).scalars().all())


def _seed_read_only_library(client, tmp_path, *, n_issues: int = 2) -> dict:
    """One seeded series whose root is then flipped read-only."""
    data = client.portal.call(
        seed,
        client.app,
        tmp_path / "reference-library",
        [simple_series(title="Example Series", n_issues=n_issues)],
    )
    client.portal.call(_mark_root_read_only, client.app, data["root_id"])
    return data


def _assert_read_only_refusal(response) -> None:
    """The shared refusal contract: 409, the uniform error shape, and the
    structural ``read_only`` discriminator the UI classifies on."""
    assert response.status_code == 409
    body = response.json()
    assert set(body) == {"message", "errors"}
    assert "read-only reference library" in body["message"]
    assert [e["field"] for e in body["errors"]] == ["read_only"]


# --- FRG-SER-021: registration validates readability -------------------------


@pytest.mark.req("FRG-SER-021")
def test_read_only_root_registers_on_a_readable_but_unwritable_directory(
    client, tmp_path
):
    """The whole point of the feature: a real collection on a read-only mount
    registers, where the writable-root requirement refused it."""
    mount = tmp_path / "mounted-collection"
    mount.mkdir()
    os.chmod(mount, stat.S_IRUSR | stat.S_IXUSR)  # r-x: readable, not writable
    try:
        refused = client.post("/api/v1/rootfolder", json={"path": str(mount)})
        accepted = client.post(
            "/api/v1/rootfolder", json={"path": str(mount), "read_only": True}
        )
    finally:
        os.chmod(mount, stat.S_IRWXU)

    # Registered as a MANAGED root, the same path is still refused as unwritable.
    assert refused.status_code == 400
    assert "not writable" in refused.json()["message"]
    assert accepted.status_code == 201
    body = accepted.json()
    assert body["read_only"] is True
    assert body["path"] == str(mount)
    assert client.get("/api/v1/rootfolder").json()[0]["read_only"] is True


@pytest.mark.req("FRG-SER-021")
def test_read_only_registration_still_requires_readability_and_uniqueness(
    client, tmp_path
):
    """Waiving W_OK waives nothing else: an unreadable path, a missing path, and
    the duplicate/nesting guards all still refuse with a field-precise 400."""
    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    os.chmod(unreadable, 0)
    try:
        resp = client.post(
            "/api/v1/rootfolder", json={"path": str(unreadable), "read_only": True}
        )
    finally:
        os.chmod(unreadable, stat.S_IRWXU)
    assert resp.status_code == 400
    assert "not readable" in resp.json()["message"]

    missing = client.post(
        "/api/v1/rootfolder",
        json={"path": str(tmp_path / "nope"), "read_only": True},
    )
    assert missing.status_code == 400
    assert "not an existing directory" in missing.json()["message"]

    collection = tmp_path / "collection"
    (collection / "inner").mkdir(parents=True)
    assert (
        client.post(
            "/api/v1/rootfolder", json={"path": str(collection), "read_only": True}
        ).status_code
        == 201
    )
    duplicate = client.post(
        "/api/v1/rootfolder", json={"path": str(collection), "read_only": True}
    )
    assert duplicate.status_code == 400
    assert "already registered" in duplicate.json()["message"]
    nested = client.post(
        "/api/v1/rootfolder",
        json={"path": str(collection / "inner"), "read_only": True},
    )
    assert nested.status_code == 400
    assert "inside an existing root folder" in nested.json()["message"]


# --- FRG-UI-045: the resource says so ----------------------------------------


@pytest.mark.req("FRG-SER-021")
def test_series_resource_exposes_read_only_on_both_read_routes(client, tmp_path):
    """The UI cannot mark a reference series or hide the actions the backend
    would refuse unless the resource tells it (the API half of FRG-UI-045) —
    on the list AND the detail."""
    managed = client.portal.call(
        seed,
        client.app,
        tmp_path / "managed-library",
        [simple_series(title="Managed Series", cv_volume_id=2, n_issues=1)],
    )
    reference = _seed_read_only_library(client, tmp_path, n_issues=1)
    reference_id = reference["series"][0]["id"]
    managed_id = managed["series"][0]["id"]

    listed = {
        row["id"]: row["read_only"]
        for row in client.get("/api/v1/series").json()["records"]
    }
    assert listed == {reference_id: True, managed_id: False}
    assert client.get(f"/api/v1/series/{reference_id}").json()["read_only"] is True
    assert client.get(f"/api/v1/series/{managed_id}").json()["read_only"] is False


# --- FRG-SER-022: no monitoring, no acquisition ------------------------------


@pytest.mark.req("FRG-SER-022")
def test_monitor_toggle_is_refused_for_a_read_only_issue(client, tmp_path):
    data = _seed_read_only_library(client, tmp_path, n_issues=1)
    issue_id = data["series"][0]["issues"][0]["id"]
    before = client.portal.call(_issue_monitored, client.app, issue_id)

    response = client.put(f"/api/v1/issues/{issue_id}", json={"monitored": False})

    _assert_read_only_refusal(response)
    # Refused, not silently no-op'd: the flag is untouched either way, and the
    # caller was told.
    assert client.portal.call(_issue_monitored, client.app, issue_id) is before


@pytest.mark.req("FRG-SER-022")
def test_bulk_monitor_toggle_refuses_the_whole_batch(client, tmp_path):
    """One browse-only issue in the batch refuses all of it — the same
    all-or-none contract the missing-id case already has."""
    managed = client.portal.call(
        seed,
        client.app,
        tmp_path / "managed-library",
        [simple_series(title="Managed Series", cv_volume_id=2, n_issues=1)],
    )
    reference = _seed_read_only_library(client, tmp_path, n_issues=1)
    managed_issue = managed["series"][0]["issues"][0]["id"]
    reference_issue = reference["series"][0]["issues"][0]["id"]

    response = client.put(
        "/api/v1/issues/monitor",
        json={"issue_ids": [managed_issue, reference_issue], "monitored": False},
    )

    _assert_read_only_refusal(response)
    assert client.portal.call(_issue_monitored, client.app, managed_issue) is True


@pytest.mark.req("FRG-SER-022")
def test_interactive_search_is_refused_for_a_read_only_issue(client, tmp_path):
    """Refused before any indexer or ComicVine budget is spent — a browse-only
    series has nowhere to download into, so there is nothing to search for."""
    data = _seed_read_only_library(client, tmp_path, n_issues=1)
    issue_id = data["series"][0]["issues"][0]["id"]

    _assert_read_only_refusal(
        client.get("/api/v1/release", params={"issueId": issue_id})
    )


# --- FRG-SER-021: the file-mutating routes refuse ----------------------------


@pytest.mark.req("FRG-SER-021")
def test_delete_files_is_refused_while_the_rows_only_delete_still_works(
    client, tmp_path
):
    data = _seed_read_only_library(client, tmp_path, n_issues=1)
    series_id = data["series"][0]["id"]
    on_disk = Path(data["series"][0]["issues"][0]["files"][0]["path"])

    refused = client.delete(f"/api/v1/series/{series_id}", params={"deleteFiles": True})

    _assert_read_only_refusal(refused)
    assert on_disk.exists()
    # Refused UP FRONT: no delete-series-files command was queued to fail later.
    assert "delete-series-files" not in client.portal.call(
        _command_names, client.app
    )
    # Un-indexing the series is still allowed — it writes nothing to the root,
    # so the operator can always stop tracking a reference library.
    assert client.delete(f"/api/v1/series/{series_id}").status_code == 204
    assert on_disk.exists()


@pytest.mark.req("FRG-SER-021")
def test_single_issue_file_delete_is_refused(client, tmp_path):
    data = _seed_read_only_library(client, tmp_path, n_issues=1)
    file_info = data["series"][0]["issues"][0]["files"][0]

    _assert_read_only_refusal(client.delete(f"/api/v1/issuefile/{file_info['id']}"))

    assert Path(file_info["path"]).exists()


@pytest.mark.req("FRG-SER-021")
def test_rename_execute_is_refused_and_queues_nothing(client, tmp_path):
    data = _seed_read_only_library(client, tmp_path, n_issues=1)
    series_id = data["series"][0]["id"]
    on_disk = Path(data["series"][0]["issues"][0]["files"][0]["path"])

    _assert_read_only_refusal(
        client.post("/api/v1/rename", json={"seriesId": series_id})
    )

    assert on_disk.exists()
    assert "rename-series" not in client.portal.call(_command_names, client.app)


# --- FRG-SER-022: the generic command transport is not a way in ---------------


async def _grab_history_count(app) -> int:
    async with app.state.db.read_session() as session:
        return await session.scalar(
            select(func.count()).select_from(GrabHistoryRow)
        )


def _await_terminal(client, command_id: int) -> dict:
    """The command row once the worker has finished with it."""
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/command/{command_id}").json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"command {command_id} never reached a terminal status")


@pytest.mark.req("FRG-SER-022")
def test_enqueued_acquisition_commands_are_refused_by_their_handlers(
    client, tmp_path
):
    """``POST /api/v1/command`` takes any registered name with an explicit
    payload, so it reaches a search or a grab without passing the routes that
    refuse. Both handlers refuse on their own and the grab records nothing."""
    data = _seed_read_only_library(client, tmp_path, n_issues=1)
    series_id = data["series"][0]["id"]
    issue_id = data["series"][0]["issues"][0]["id"]

    search = client.post(
        "/api/v1/command",
        json={
            "name": "issue-search",
            "payload": {"series_id": series_id, "issue_id": issue_id},
        },
    )
    grab = client.post(
        "/api/v1/command",
        json={
            "name": "grab-release",
            "payload": {
                "indexer_id": 1,
                "guid": "synthetic-guid-1",
                "link": "https://indexer.example.com/nzb/1",
                "title": "Example Series 001 (2024)",
                "series_id": series_id,
                "issue_id": issue_id,
            },
        },
    )

    for created in (search, grab):
        assert created.status_code == 201
        record = _await_terminal(client, created.json()["id"])
        assert record["status"] == "failed"
        assert "read-only reference library" in record["error"]
    assert client.portal.call(_grab_history_count, client.app) == 0


@pytest.mark.req("FRG-SER-022")
def test_series_edit_refuses_monitoring_and_path_changes(client, tmp_path):
    data = _seed_read_only_library(client, tmp_path, n_issues=1)
    series_id = data["series"][0]["id"]

    _assert_read_only_refusal(
        client.put(f"/api/v1/series/{series_id}", json={"monitored": True})
    )
    _assert_read_only_refusal(
        client.put(
            f"/api/v1/series/{series_id}",
            json={"path": str(tmp_path / "reference-library" / "Renamed")},
        )
    )
