"""FRG-API-019 — GET /api/v1/pull: the weekly pull read endpoint."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.config import Settings
from foragerr.library import repo as library_repo
from foragerr.pull import repo as pull_repo
from foragerr.pull.models import ParsedPullEntry
from foragerr.pull.projection import current_week

WEEK = "2026-W28"
MONDAY = dt.date(2026, 7, 6)
IN_WEEK = MONDAY + dt.timedelta(days=2)


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


async def _format_profile_id(db):
    from sqlalchemy import select

    from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

    async with db.read_session() as session:
        return (
            await session.execute(
                select(FormatProfileRow.id).where(
                    FormatProfileRow.name == DEFAULT_PROFILE_NAME
                )
            )
        ).scalar_one()


async def _seed_week(db, tmp_path) -> dict[str, int]:
    """One watched series with: a monitored+fileless linked issue (missing/
    wanted), a has-file linked issue (downloaded), and a stored unmatched
    pull entry with no issue link at all."""
    profile_id = await _format_profile_id(db)
    root = tmp_path / "lib-root"
    root.mkdir(exist_ok=True)
    async with db.write_session() as session:
        rf = await library_repo.create_root_folder(session, str(root))
        series = await library_repo.create_series(
            session,
            cv_volume_id=1,
            title="Saga",
            start_year=2024,
            format_profile_id=profile_id,
            root_folder_id=rf.id,
            path=str(root / "Saga"),
            monitored=True,
            publisher="Image",
        )
        await session.flush()
        missing = await library_repo.create_issue(
            session,
            series_id=series.id,
            cv_issue_id=101,
            issue_number="1",
            store_date=IN_WEEK,
            monitored=True,
        )
        downloaded = await library_repo.create_issue(
            session,
            series_id=series.id,
            cv_issue_id=102,
            issue_number="2",
            store_date=IN_WEEK,
            monitored=True,
        )
        await session.flush()
        await library_repo.add_issue_file(
            session, issue_id=downloaded.id, path=str(root / "saga-2.cbz"), size=1
        )
    async with db.write_session() as session:
        rows = await pull_repo.replace_week(
            session,
            WEEK,
            [
                ParsedPullEntry(
                    series_name="Unknown Comic",
                    issue_number="1",
                    release_date=IN_WEEK,
                    publisher="Some Press",
                )
            ],
        )
        unmatched_entry_id = rows[0].id
    return {
        "series_id": series.id,
        "missing_id": missing.id,
        "downloaded_id": downloaded.id,
        "unmatched_entry_id": unmatched_entry_id,
    }


_ENVELOPE_KEYS = {"page", "pageSize", "sortKey", "sortDirection", "totalRecords", "records"}


@pytest.mark.req("FRG-API-019")
def test_empty_week_returns_empty_envelope_not_error(client):
    resp = client.get("/api/v1/pull?week=2099-W01")
    assert resp.status_code == 200
    body = resp.json()
    assert _ENVELOPE_KEYS <= body.keys()
    assert body["totalRecords"] == 0
    assert body["records"] == []


@pytest.mark.req("FRG-API-019")
@pytest.mark.req("FRG-PULL-001")
def test_stored_and_matched_week_derives_fields_correctly(client, tmp_path):
    ids = client.portal.call(_seed_week, client.app.state.db, tmp_path)
    body = client.get(f"/api/v1/pull?week={WEEK}&pageSize=200").json()
    assert _ENVELOPE_KEYS <= body.keys()
    by_issue = {r["matchedIssueId"]: r for r in body["records"] if r["matchedIssueId"] is not None}

    missing_row = by_issue[ids["missing_id"]]
    assert missing_row["state"] == "missing_wanted"
    assert missing_row["series"] == {"id": ids["series_id"], "title": "Saga"}

    downloaded_row = by_issue[ids["downloaded_id"]]
    assert downloaded_row["state"] == "downloaded"

    unmatched_rows = [r for r in body["records"] if r["matchedIssueId"] is None]
    assert len(unmatched_rows) == 1
    assert unmatched_rows[0]["matchType"] == "unmatched"
    assert unmatched_rows[0]["state"] is None
    assert unmatched_rows[0]["id"] == ids["unmatched_entry_id"]

    # No secret of any kind is present anywhere in the payload.
    dumped = str(body).lower()
    for forbidden in ("apikey", "api_key", "token", "password", "secret"):
        assert forbidden not in dumped


@pytest.mark.req("FRG-API-019")
def test_omitted_week_defaults_to_current_week(client, tmp_path, monkeypatch):
    import foragerr.api.pull as pull_api

    monkeypatch.setattr(pull_api, "current_week", lambda: WEEK)
    ids = client.portal.call(_seed_week, client.app.state.db, tmp_path)
    body = client.get("/api/v1/pull?pageSize=200").json()
    got = {r["matchedIssueId"] for r in body["records"] if r["matchedIssueId"] is not None}
    assert ids["missing_id"] in got


@pytest.mark.req("FRG-API-019")
def test_malformed_week_is_a_400_naming_the_field(client):
    for bad in ("not-a-week", "2026", "2026-W99"):
        resp = client.get(f"/api/v1/pull?week={bad}")
        assert resp.status_code == 400, (bad, resp.status_code, resp.text)
        body = resp.json()
        assert body["errors"][0]["field"] == "week"


@pytest.mark.req("FRG-API-019")
def test_paging_envelope_and_size_cap(client, tmp_path):
    client.portal.call(_seed_week, client.app.state.db, tmp_path)

    at_cap = client.get(f"/api/v1/pull?week={WEEK}&pageSize=200")
    assert at_cap.status_code == 200
    assert at_cap.json()["pageSize"] == 200

    over_cap = client.get(f"/api/v1/pull?week={WEEK}&pageSize=201")
    assert over_cap.status_code == 400

    resp = client.get(f"/api/v1/pull?week={WEEK}&sortKey=bogus")
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "sortKey"


@pytest.mark.req("FRG-API-019")
def test_read_only_no_mutation_possible(client, tmp_path):
    """GET is the only method the router exposes; issuing it never writes
    anything (verified by round-tripping the same week twice with identical
    results, and that non-GET verbs are refused)."""
    client.portal.call(_seed_week, client.app.state.db, tmp_path)
    first = client.get(f"/api/v1/pull?week={WEEK}&pageSize=200").json()
    second = client.get(f"/api/v1/pull?week={WEEK}&pageSize=200").json()
    assert first == second

    for method in ("post", "put", "patch", "delete"):
        resp = getattr(client, method)(f"/api/v1/pull?week={WEEK}")
        assert resp.status_code in (404, 405)
