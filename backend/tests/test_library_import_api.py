"""HTTP contract tests for the library-import router (FRG-IMP-023 API surface).

Scan dispatch, the paged staging envelope, the PATCH review verbs
(confirm / override / skip), and the execute dispatch — status codes, error
shapes, and validation. Flow correctness (grouping, proposals, placement) is
covered by ``tests/library/test_library_import_*.py``, not re-tested here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flows_support import FakeCV, build_factory, flows_settings
from foragerr.app import create_app
from foragerr.db import utcnow
from foragerr.library import repo
from foragerr.library.flows import encode_group_files
from foragerr.library.models import LibraryImportGroupRow


@pytest.fixture(autouse=True)
def _reset_cv_gate():
    """This file lives flat under ``backend/tests/`` so it does not inherit the
    library package's autouse rate-gate isolation — mirror it here."""
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
    root.mkdir(exist_ok=True)
    return client.portal.call(_create_root_folder, client.app, root)


async def _seed_group(app, root_folder_id: int, overrides: dict) -> int:
    values = dict(
        matching_key="saga",
        root_folder_id=root_folder_id,
        folder="/library/Saga (2012)",
        files=encode_group_files([("/library/Saga (2012)/Saga 001 (2012).cbz", 42)]),
        confidence=0.9,
        proposed_cv_volume_id=101,
        confirmed_cv_volume_id=None,
        state="proposed",
        message=None,
        scanned_at=utcnow(),
    )
    values.update(overrides)
    async with app.state.db.write_session() as session:
        row = LibraryImportGroupRow(**values)
        session.add(row)
        await session.flush()
        return row.id


def seed_group(client, root_folder_id: int, **overrides) -> int:
    return client.portal.call(_seed_group, client.app, root_folder_id, overrides)


# --- scan --------------------------------------------------------------------


@pytest.mark.req("FRG-IMP-023")
def test_scan_enqueues_a_command_for_a_registered_root(client, tmp_path):
    root_id = make_root_folder(client, tmp_path)

    resp = client.post("/api/v1/library-import/scan", json={"rootFolderId": root_id})

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "library-import-scan"
    assert body["payload"] == {"root_folder_id": root_id}
    # It rides the real command backbone (trackable via GET /command/{id}).
    assert client.get(f"/api/v1/command/{body['id']}").status_code == 200


@pytest.mark.req("FRG-IMP-023")
def test_scan_of_an_unknown_root_folder_is_404(client):
    resp = client.post("/api/v1/library-import/scan", json={"rootFolderId": 999})
    assert resp.status_code == 404
    assert "message" in resp.json()


# --- listing -----------------------------------------------------------------


@pytest.mark.req("FRG-IMP-023")
def test_listing_is_a_paged_envelope_of_groups(client, tmp_path):
    root_id = make_root_folder(client, tmp_path)
    seed_group(client, root_id, matching_key="saga")
    seed_group(
        client,
        root_id,
        matching_key="paper girls",
        state="no_match",
        proposed_cv_volume_id=None,
        message="no comicvine results for 'paper girls'",
    )

    resp = client.get("/api/v1/library-import", params={"rootFolderId": root_id})

    assert resp.status_code == 200
    body = resp.json()
    assert body["totalRecords"] == 2
    assert body["sortKey"] == "matching_key"
    keys = [record["matchingKey"] for record in body["records"]]
    assert keys == sorted(keys)
    saga = next(r for r in body["records"] if r["matchingKey"] == "saga")
    assert saga["proposedCvVolumeId"] == 101
    assert saga["state"] == "proposed"
    assert saga["files"][0]["name"] == "Saga 001 (2012).cbz"
    no_match = next(r for r in body["records"] if r["matchingKey"] == "paper girls")
    assert no_match["state"] == "no_match"
    assert "no comicvine results" in no_match["message"]


@pytest.mark.req("FRG-IMP-023")
def test_listing_validation_unknown_root_404_and_bad_sort_key_400(client, tmp_path):
    assert (
        client.get("/api/v1/library-import", params={"rootFolderId": 999}).status_code
        == 404
    )
    root_id = make_root_folder(client, tmp_path)
    resp = client.get(
        "/api/v1/library-import",
        params={"rootFolderId": root_id, "sortKey": "evil; DROP TABLE"},
    )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "sortKey"


# --- PATCH review verbs --------------------------------------------------------


@pytest.mark.req("FRG-IMP-023")
def test_patch_confirms_the_proposed_match(client, tmp_path):
    root_id = make_root_folder(client, tmp_path)
    group_id = seed_group(client, root_id)

    resp = client.patch(
        f"/api/v1/library-import/groups/{group_id}", json={"state": "confirmed"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "confirmed"
    assert body["confirmedCvVolumeId"] == 101  # adopted from the proposal


@pytest.mark.req("FRG-IMP-023")
def test_patch_confirm_without_any_proposal_is_400(client, tmp_path):
    root_id = make_root_folder(client, tmp_path)
    group_id = seed_group(
        client, root_id, proposed_cv_volume_id=None, state="no_match"
    )
    resp = client.patch(
        f"/api/v1/library-import/groups/{group_id}", json={"state": "confirmed"}
    )
    assert resp.status_code == 400
    assert "cvVolumeId" in resp.json()["message"]


@pytest.mark.req("FRG-IMP-023")
def test_patch_override_validates_the_volume_against_comicvine(
    client, tmp_path, monkeypatch
):
    root_id = make_root_folder(client, tmp_path)
    group_id = seed_group(client, root_id)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(202, name="Paper Girls").handler(),
    )
    monkeypatch.setattr(
        "foragerr.api.library_import.comicvine_factory", lambda _settings: factory
    )

    good = client.patch(
        f"/api/v1/library-import/groups/{group_id}", json={"cvVolumeId": 202}
    )
    assert good.status_code == 200
    assert good.json()["confirmedCvVolumeId"] == 202
    assert good.json()["state"] == "confirmed"

    # A volume ComicVine cannot supply is rejected 400 and nothing changes.
    bad = client.patch(
        f"/api/v1/library-import/groups/{group_id}", json={"cvVolumeId": 999}
    )
    assert bad.status_code == 400
    assert "999" in bad.json()["message"]
    unchanged = client.get(
        "/api/v1/library-import", params={"rootFolderId": root_id}
    ).json()["records"][0]
    assert unchanged["confirmedCvVolumeId"] == 202


@pytest.mark.req("FRG-IMP-023")
def test_patch_skip_and_unknown_group_404(client, tmp_path):
    root_id = make_root_folder(client, tmp_path)
    group_id = seed_group(client, root_id)

    resp = client.patch(
        f"/api/v1/library-import/groups/{group_id}", json={"state": "skipped"}
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "skipped"

    assert (
        client.patch(
            "/api/v1/library-import/groups/999999", json={"state": "skipped"}
        ).status_code
        == 404
    )
    # An empty patch names the problem rather than 500ing.
    assert (
        client.patch(
            f"/api/v1/library-import/groups/{group_id}", json={}
        ).status_code
        == 400
    )


# --- execute -------------------------------------------------------------------


@pytest.mark.req("FRG-IMP-023")
def test_execute_enqueues_the_bulk_import_for_confirmed_groups(
    client, tmp_path, monkeypatch
):
    root_id = make_root_folder(client, tmp_path)
    group_id = seed_group(
        client, root_id, state="confirmed", confirmed_cv_volume_id=101
    )
    # The enqueued command may start running in the background: route every
    # ComicVine call site at the fake so no live call can escape.
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(101, name="Saga").issues(101, []).handler(),
    )
    for seam in (
        "foragerr.library.flows.add.comicvine_factory",
        "foragerr.library.flows.refresh.comicvine_factory",
        "foragerr.library.flows.library_import.comicvine_factory",
    ):
        monkeypatch.setattr(seam, lambda _settings: factory)

    resp = client.post(
        "/api/v1/library-import/execute",
        json={
            "groupIds": [group_id],
            "addOptions": {"monitorStrategy": "all", "searchOnAdd": False},
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "library-import"
    assert body["payload"]["group_ids"] == [group_id]
    assert body["payload"]["monitor_strategy"] == "all"


@pytest.mark.req("FRG-IMP-023")
def test_execute_validation_errors(client, tmp_path):
    root_id = make_root_folder(client, tmp_path)
    confirmed = seed_group(
        client, root_id, state="confirmed", confirmed_cv_volume_id=101
    )
    unconfirmed = seed_group(client, root_id, matching_key="paper girls")

    # Empty selection.
    assert (
        client.post(
            "/api/v1/library-import/execute", json={"groupIds": []}
        ).status_code
        == 400
    )
    # Unknown group id -> 404.
    assert (
        client.post(
            "/api/v1/library-import/execute", json={"groupIds": [confirmed, 999999]}
        ).status_code
        == 404
    )
    # A group that was never confirmed -> 400 naming it.
    resp = client.post(
        "/api/v1/library-import/execute", json={"groupIds": [unconfirmed]}
    )
    assert resp.status_code == 400
    assert str(unconfirmed) in resp.json()["message"]
    # Bad monitor strategy / unknown format profile.
    assert (
        client.post(
            "/api/v1/library-import/execute",
            json={
                "groupIds": [confirmed],
                "addOptions": {"monitorStrategy": "sometimes"},
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/library-import/execute",
            json={"groupIds": [confirmed], "addOptions": {"formatProfileId": 999}},
        ).status_code
        == 400
    )
