"""FRG-API-011 — GET /api/v1/history: the paged single-source event feed."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from foragerr.app import create_app
from foragerr.config import Settings
from foragerr.importer import history


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


async def _seed_series_issue(db, tmp_path) -> tuple[int, int]:
    from foragerr.library import repo
    from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

    root = tmp_path / "lib-root"
    root.mkdir(exist_ok=True)
    async with db.read_session() as session:
        profile_id = (
            await session.execute(
                select(FormatProfileRow.id).where(
                    FormatProfileRow.name == DEFAULT_PROFILE_NAME
                )
            )
        ).scalar_one()
    async with db.write_session() as session:
        rf = await repo.create_root_folder(session, str(root))
        series = await repo.create_series(
            session,
            cv_volume_id=987654,
            title="Spawn",
            start_year=2024,
            format_profile_id=profile_id,
            root_folder_id=rf.id,
            path=str(root / "Spawn"),
            monitored=True,
        )
        await session.flush()
        issue = await repo.create_issue(
            session,
            series_id=series.id,
            cv_issue_id=123456,
            issue_number="1",
            cover_date=dt.date(2024, 1, 1),
            monitored=True,
        )
        await session.flush()
        return series.id, issue.id


async def _seed_events(db, tmp_path) -> tuple[int, int]:
    """A grabbed+imported pair for one series plus an unrelated blocked event."""
    series_id, issue_id = await _seed_series_issue(db, tmp_path)
    base = dt.datetime(2026, 7, 1, 12, 0, 0)
    async with db.write_session() as session:
        history.record_event(
            session,
            event_type=history.EVENT_GRABBED,
            series_id=series_id,
            issue_id=issue_id,
            download_id="nzo-1",
            source_title="Spawn 001 (2024)",
            source=history.SOURCE_DOWNLOAD,
            data={"indexer": "DogNZB", "protocol": "usenet"},
            now=base,
        )
        history.record_event(
            session,
            event_type=history.EVENT_IMPORTED,
            series_id=series_id,
            issue_id=issue_id,
            download_id="nzo-1",
            source_title="Spawn 001 (2024)",
            source=history.SOURCE_DOWNLOAD,
            data={"imported_path": "/lib/Spawn/Spawn 001.cbz", "size": 9},
            now=base + dt.timedelta(minutes=5),
        )
        history.record_event(
            session,
            event_type=history.EVENT_IMPORT_BLOCKED,
            download_id="nzo-2",
            source_title="Unknown Series 001",
            source=history.SOURCE_DOWNLOAD,
            data={"reasons": ["no matching series"]},
            now=base + dt.timedelta(minutes=10),
        )
    return series_id, issue_id


@pytest.mark.req("FRG-API-011")
def test_history_paged_envelope_newest_first_with_nested_resources(
    client, tmp_path
):
    series_id, issue_id = client.portal.call(
        _seed_events, client.app.state.db, tmp_path
    )
    body = client.get("/api/v1/history").json()
    assert {
        "page",
        "pageSize",
        "sortKey",
        "sortDirection",
        "totalRecords",
        "records",
    } <= body.keys()
    assert body["totalRecords"] == 3
    assert body["sortKey"] == "created_at" and body["sortDirection"] == "desc"
    # Newest first: blocked, imported, grabbed.
    assert [r["eventType"] for r in body["records"]] == [
        "import_blocked",
        "imported",
        "grabbed",
    ]

    imported = body["records"][1]
    assert imported["sourceTitle"] == "Spawn 001 (2024)"
    assert imported["downloadId"] == "nzo-1"
    assert imported["data"]["imported_path"] == "/lib/Spawn/Spawn 001.cbz"
    assert imported["series"] == {"id": series_id, "title": "Spawn"}
    assert imported["issue"] == {"id": issue_id, "issueNumber": "1", "title": None}
    assert imported["date"] is not None

    # The grab-and-import cycle shares one downloadId (scenario 1).
    cycle = [r for r in body["records"] if r["downloadId"] == "nzo-1"]
    assert {r["eventType"] for r in cycle} == {"grabbed", "imported"}

    # An event with no library linkage carries null nested objects, not a 500.
    blocked = body["records"][0]
    assert blocked["series"] is None and blocked["issue"] is None
    assert blocked["data"]["reasons"] == ["no matching series"]


@pytest.mark.req("FRG-API-011")
def test_history_filters_by_event_type_and_series(client, tmp_path):
    series_id, _ = client.portal.call(_seed_events, client.app.state.db, tmp_path)

    by_type = client.get("/api/v1/history?eventType=import_blocked").json()
    assert by_type["totalRecords"] == 1
    assert by_type["records"][0]["eventType"] == "import_blocked"

    by_series = client.get(f"/api/v1/history?seriesId={series_id}").json()
    assert by_series["totalRecords"] == 2
    assert all(r["series"]["id"] == series_id for r in by_series["records"])

    combined = client.get(
        f"/api/v1/history?eventType=grabbed&seriesId={series_id}"
    ).json()
    assert combined["totalRecords"] == 1
    assert combined["records"][0]["eventType"] == "grabbed"

    other = client.get("/api/v1/history?seriesId=99999").json()
    assert other["totalRecords"] == 0


@pytest.mark.req("FRG-API-011")
def test_history_rejects_unknown_event_type_and_sort_key(client):
    resp = client.get("/api/v1/history?eventType=exploded")
    assert resp.status_code == 400
    body = resp.json()
    assert body["errors"][0]["field"] == "eventType"

    resp = client.get("/api/v1/history?sortKey=guid")
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "sortKey"

    # event_type IS a whitelisted sort key.
    ok = client.get("/api/v1/history?sortKey=event_type&sortDirection=asc")
    assert ok.status_code == 200


@pytest.mark.req("FRG-API-011")
def test_history_pages_are_stable_slices(client, tmp_path):
    client.portal.call(_seed_events, client.app.state.db, tmp_path)
    page1 = client.get("/api/v1/history?page=1&pageSize=2").json()
    page2 = client.get("/api/v1/history?page=2&pageSize=2").json()
    assert page1["totalRecords"] == page2["totalRecords"] == 3
    assert len(page1["records"]) == 2 and len(page2["records"]) == 1
    ids = [r["id"] for r in page1["records"] + page2["records"]]
    assert len(set(ids)) == 3  # no overlap between pages
