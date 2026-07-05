"""HTTP contract tests for the issues router (FRG-API-004, FRG-API-006).

Exercises status codes, response shapes, the paging envelope, sort-key
whitelisting, the issue-number-stays-a-string contract, and single/bulk
monitored-toggle atomicity. Flow/reconciliation correctness is already
covered by ``backend/tests/library/test_flows_*.py`` — not re-tested here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from foragerr.app import create_app
from foragerr.library import repo
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

from http_support import make_settings


# --- fixtures ------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(make_settings(cfg))
    with TestClient(app) as c:
        yield c


async def _format_profile_id(app) -> int:
    async with app.state.db.read_session() as session:
        return await session.scalar(
            select(FormatProfileRow.id).where(FormatProfileRow.name == DEFAULT_PROFILE_NAME)
        )


async def _root_folder_id(app, path: Path) -> int:
    async with app.state.db.write_session() as session:
        row = await repo.create_root_folder(session, str(path))
        return row.id


async def _create_series(
    app, root_folder_id: int, format_profile_id: int, cv_volume_id: int
) -> int:
    async with app.state.db.write_session() as session:
        row = await repo.create_series(
            session,
            cv_volume_id=cv_volume_id,
            title=f"Series {cv_volume_id}",
            root_folder_id=root_folder_id,
            format_profile_id=format_profile_id,
            path=f"/tmp/series-{cv_volume_id}",
        )
        return row.id


async def _create_issue(
    app, series_id: int, cv_issue_id: int, issue_number: str | None, with_file: bool
) -> int:
    async with app.state.db.write_session() as session:
        row = await repo.create_issue(
            session,
            series_id=series_id,
            cv_issue_id=cv_issue_id,
            issue_number=issue_number,
        )
        if with_file:
            await repo.add_issue_file(
                session, issue_id=row.id, path=f"/tmp/issue-{cv_issue_id}.cbz", size=1024
            )
        return row.id


def make_series(client, tmp_path: Path, cv_volume_id: int = 1) -> int:
    root = tmp_path / f"root-{cv_volume_id}"
    root.mkdir()
    root_id = client.portal.call(_root_folder_id, client.app, root)
    profile_id = client.portal.call(_format_profile_id, client.app)
    return client.portal.call(
        _create_series, client.app, root_id, profile_id, cv_volume_id
    )


def make_issue(
    client, series_id: int, cv_issue_id: int, issue_number: str | None, with_file: bool = False
) -> int:
    return client.portal.call(
        _create_issue, client.app, series_id, cv_issue_id, issue_number, with_file
    )


# --- list --------------------------------------------------------------------


@pytest.mark.req("FRG-API-004")
@pytest.mark.req("FRG-API-006")
def test_issue_list_is_a_paged_envelope_scoped_by_series(client, tmp_path):
    series_id = make_series(client, tmp_path)
    other_series_id = make_series(client, tmp_path, cv_volume_id=2)
    make_issue(client, series_id, 1, "1")
    make_issue(client, series_id, 2, "2")
    make_issue(client, other_series_id, 3, "1")

    response = client.get("/api/v1/issues", params={"seriesId": series_id})
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
    assert all(r["series_id"] == series_id for r in body["records"])


@pytest.mark.req("FRG-API-004")
def test_issue_list_orders_by_persisted_ordering_key(client, tmp_path):
    series_id = make_series(client, tmp_path)
    make_issue(client, series_id, 1, "10")
    make_issue(client, series_id, 2, "2")
    make_issue(client, series_id, 3, "1")

    response = client.get("/api/v1/issues", params={"seriesId": series_id, "pageSize": 50})
    numbers = [r["issue_number"] for r in response.json()["records"]]
    assert numbers == ["1", "2", "10"]  # reading order, not lexicographic


@pytest.mark.req("FRG-API-004")
def test_issue_numbers_round_trip_as_strings_never_coerced(client, tmp_path):
    series_id = make_series(client, tmp_path)
    make_issue(client, series_id, 1, "1.5")
    make_issue(client, series_id, 2, "1.MU")

    response = client.get("/api/v1/issues", params={"seriesId": series_id, "pageSize": 50})
    numbers = {r["issue_number"] for r in response.json()["records"]}
    assert numbers == {"1.5", "1.MU"}
    # A raw-text check on the wire, guarding against any silent
    # int/float coercion Pydantic could otherwise apply (a coerced float
    # would serialize as a bare `1.5` with no surrounding quotes).
    assert '"1.5"' in response.text
    assert '"1.MU"' in response.text


@pytest.mark.req("FRG-API-004")
def test_issue_list_includes_file_info_when_present(client, tmp_path):
    series_id = make_series(client, tmp_path)
    with_file_id = make_issue(client, series_id, 1, "1", with_file=True)
    without_file_id = make_issue(client, series_id, 2, "2", with_file=False)

    response = client.get("/api/v1/issues", params={"seriesId": series_id, "pageSize": 50})
    by_id = {r["id"]: r for r in response.json()["records"]}
    assert by_id[with_file_id]["has_file"] is True
    assert by_id[with_file_id]["file"]["path"] == "/tmp/issue-1.cbz"
    assert by_id[with_file_id]["file"]["size"] == 1024
    assert by_id[without_file_id]["has_file"] is False
    assert by_id[without_file_id]["file"] is None


@pytest.mark.req("FRG-API-006")
def test_issue_list_unknown_sort_key_is_400(client, tmp_path):
    series_id = make_series(client, tmp_path)
    response = client.get(
        "/api/v1/issues",
        params={"seriesId": series_id, "sortKey": "title; DROP TABLE issues--"},
    )
    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"message", "errors"}
    assert body["errors"][0]["field"] == "sortKey"


# --- single toggle -------------------------------------------------------


@pytest.mark.req("FRG-API-004")
def test_single_monitored_toggle_updates_only_that_issue(client, tmp_path):
    series_id = make_series(client, tmp_path)
    issue_id = make_issue(client, series_id, 1, "1")
    sibling_id = make_issue(client, series_id, 2, "2")

    response = client.put(f"/api/v1/issues/{issue_id}", json={"monitored": False})
    assert response.status_code == 200
    assert response.json()["monitored"] is False

    listing = client.get(
        "/api/v1/issues", params={"seriesId": series_id, "pageSize": 50}
    ).json()
    by_id = {r["id"]: r for r in listing["records"]}
    assert by_id[issue_id]["monitored"] is False
    assert by_id[sibling_id]["monitored"] is True  # untouched


@pytest.mark.req("FRG-API-004")
def test_single_monitored_toggle_unknown_id_is_404(client):
    response = client.put("/api/v1/issues/999999", json={"monitored": False})
    assert response.status_code == 404


# --- bulk toggle ----------------------------------------------------------


@pytest.mark.req("FRG-API-004")
def test_bulk_monitored_toggle_applies_to_all_named_issues(client, tmp_path):
    series_id = make_series(client, tmp_path)
    ids = [make_issue(client, series_id, i, str(i)) for i in range(1, 4)]

    response = client.put(
        "/api/v1/issues/monitor", json={"issue_ids": ids, "monitored": False}
    )
    assert response.status_code == 200

    listing = client.get(
        "/api/v1/issues", params={"seriesId": series_id, "pageSize": 50}
    ).json()
    assert all(r["monitored"] is False for r in listing["records"])


@pytest.mark.req("FRG-API-004")
def test_bulk_monitored_toggle_is_atomic_all_or_none(client, tmp_path):
    """A bad id anywhere in the batch rolls back the WHOLE request — the
    good ids' monitored flags must be untouched, not partially applied."""
    series_id = make_series(client, tmp_path)
    ids = [make_issue(client, series_id, i, str(i)) for i in range(1, 4)]

    response = client.put(
        "/api/v1/issues/monitor",
        json={"issue_ids": ids + [999999], "monitored": False},
    )
    assert response.status_code == 404

    listing = client.get(
        "/api/v1/issues", params={"seriesId": series_id, "pageSize": 50}
    ).json()
    assert all(r["monitored"] is True for r in listing["records"])  # nothing changed
