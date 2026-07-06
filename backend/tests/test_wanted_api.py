"""FRG-API-012 — GET /api/v1/wanted/missing: the DERIVED missing list."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from foragerr.app import create_app
from foragerr.config import Settings
from foragerr.library import repo


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


async def _seed(db, tmp_path) -> dict[str, int]:
    """One monitored series with a released missing issue, an unreleased one,
    and an unmonitored one; a second series for the title sort."""
    from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

    root = tmp_path / "lib-root"
    root.mkdir(exist_ok=True)
    today = dt.date.today()
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

        async def _series(title: str, cv_volume_id: int):
            s = await repo.create_series(
                session,
                cv_volume_id=cv_volume_id,
                title=title,
                start_year=2024,
                format_profile_id=profile_id,
                root_folder_id=rf.id,
                path=str(root / title),
                monitored=True,
            )
            await session.flush()
            return s

        spawn = await _series("Spawn", 100)
        batman = await _series("Batman", 200)

        async def _issue(series_id, cv_issue_id, number, cover, monitored=True):
            issue = await repo.create_issue(
                session,
                series_id=series_id,
                cv_issue_id=cv_issue_id,
                issue_number=number,
                cover_date=cover,
                monitored=monitored,
            )
            await session.flush()
            return issue

        released = await _issue(spawn.id, 1001, "1", today - dt.timedelta(days=30))
        unreleased = await _issue(spawn.id, 1002, "2", today + dt.timedelta(days=30))
        unmonitored = await _issue(
            spawn.id, 1003, "3", today - dt.timedelta(days=30), monitored=False
        )
        other = await _issue(batman.id, 2001, "404", today - dt.timedelta(days=60))
        return {
            "spawn": spawn.id,
            "batman": batman.id,
            "released": released.id,
            "unreleased": unreleased.id,
            "unmonitored": unmonitored.id,
            "other": other.id,
        }


@pytest.mark.req("FRG-API-012")
def test_missing_lists_only_monitored_released_fileless_issues(client, tmp_path):
    ids = client.portal.call(_seed, client.app.state.db, tmp_path)
    body = client.get("/api/v1/wanted/missing").json()
    assert {
        "page",
        "pageSize",
        "sortKey",
        "sortDirection",
        "totalRecords",
        "records",
    } <= body.keys()
    got = {r["id"] for r in body["records"]}
    assert got == {ids["released"], ids["other"]}
    # Unreleased and unmonitored issues are excluded by the derived query.
    assert ids["unreleased"] not in got and ids["unmonitored"] not in got

    # Default sort: release date ascending — Batman (older) first.
    assert body["sortKey"] == "release_date" and body["sortDirection"] == "asc"
    assert [r["id"] for r in body["records"]] == [ids["other"], ids["released"]]

    rec = body["records"][1]
    assert rec["series"] == {"id": ids["spawn"], "title": "Spawn"}
    assert rec["issue_number"] == "1"  # verbatim string, never coerced
    assert rec["monitored"] is True
    assert "has_file" not in rec  # a wanted issue by definition has no file


@pytest.mark.req("FRG-API-012")
def test_import_removes_and_delete_returns_with_no_status_write(client, tmp_path):
    """The list is DERIVED: adding an issue_files row (what an import does) is
    the ONLY thing that removes an issue, and deleting the row is the ONLY
    thing that returns it — no wanted-status column is ever written."""
    ids = client.portal.call(_seed, client.app.state.db, tmp_path)
    db = client.app.state.db

    async def _import_file():
        async with db.write_session() as session:
            row = await repo.add_issue_file(
                session, issue_id=ids["released"], path="/lib/Spawn 001.cbz", size=9
            )
            await session.flush()
            return row.id

    async def _delete_file(file_id: int):
        async with db.write_session() as session:
            await repo.remove_issue_file(session, file_id)

    assert ids["released"] in {
        r["id"] for r in client.get("/api/v1/wanted/missing").json()["records"]
    }

    file_id = client.portal.call(_import_file)
    assert ids["released"] not in {
        r["id"] for r in client.get("/api/v1/wanted/missing").json()["records"]
    }

    client.portal.call(_delete_file, file_id)
    assert ids["released"] in {
        r["id"] for r in client.get("/api/v1/wanted/missing").json()["records"]
    }

    # No stored status anywhere: the issues table has no wanted/status column
    # for this surface to have written (FRG-API-012 scenario 2).
    from foragerr.library.models import IssueRow

    assert not any("wanted" in c.name for c in IssueRow.__table__.columns)


@pytest.mark.req("FRG-API-012")
def test_missing_sorts_by_series_title_and_rejects_unknown_keys(client, tmp_path):
    ids = client.portal.call(_seed, client.app.state.db, tmp_path)
    body = client.get(
        "/api/v1/wanted/missing?sortKey=series_title&sortDirection=asc"
    ).json()
    assert [r["series"]["title"] for r in body["records"]] == ["Batman", "Spawn"]

    resp = client.get("/api/v1/wanted/missing?sortKey=path")
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "sortKey"
