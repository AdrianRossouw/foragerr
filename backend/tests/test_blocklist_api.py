"""FRG-UI-017 — the blocklist read/remove surface:
GET /api/v1/blocklist, DELETE /blocklist/{id}, POST /blocklist/delete."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from foragerr.app import create_app
from foragerr.config import Settings
from foragerr.downloads.models import BlocklistRow
from foragerr.downloads.stores import load_blocklist_store


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


async def _insert_block(
    db,
    *,
    series_id: int | None = None,
    issue_id: int | None = None,
    guid: str | None = "G1",
    title: str = "Spawn 001 (2024)",
    message: str | None = "download failed: unpack error",
    created_at: dt.datetime | None = None,
) -> int:
    async with db.write_session() as session:
        row = BlocklistRow(
            series_id=series_id,
            issue_id=issue_id,
            source_title=title,
            guid=guid,
            indexer_id=7,
            indexer_name="DogNZB",
            size_bytes=12345,
            protocol="usenet",
            source="indexer",
            download_id="f1",
            message=message,
            created_at=created_at or dt.datetime(2026, 7, 1, 12, 0, 0),
        )
        session.add(row)
        await session.flush()
        return row.id


@pytest.mark.req("FRG-UI-017")
def test_blocklist_paged_envelope_newest_first_with_nested_resources(
    client, tmp_path
):
    db = client.app.state.db
    series_id, issue_id = client.portal.call(_seed_series_issue, db, tmp_path)
    older = client.portal.call(
        lambda: _insert_block(
            db,
            series_id=series_id,
            issue_id=issue_id,
            created_at=dt.datetime(2026, 7, 1, 12, 0, 0),
        )
    )
    newer = client.portal.call(
        lambda: _insert_block(
            db, guid="G2", created_at=dt.datetime(2026, 7, 2, 12, 0, 0)
        )
    )

    body = client.get("/api/v1/blocklist").json()
    assert {
        "page",
        "pageSize",
        "sortKey",
        "sortDirection",
        "totalRecords",
        "records",
    } <= body.keys()
    assert body["totalRecords"] == 2
    assert body["sortKey"] == "created_at" and body["sortDirection"] == "desc"
    assert [r["id"] for r in body["records"]] == [newer, older]  # newest first

    linked = body["records"][1]
    assert linked["series"] == {"id": series_id, "title": "Spawn"}
    assert linked["issue"] == {"id": issue_id, "issueNumber": "1", "title": None}
    assert linked["sourceTitle"] == "Spawn 001 (2024)"
    assert linked["guid"] == "G1" and linked["indexer"] == "DogNZB"
    assert linked["message"] == "download failed: unpack error"  # verbatim
    assert linked["downloadId"] == "f1"

    unlinked = body["records"][0]
    assert unlinked["series"] is None and unlinked["issue"] is None

    resp = client.get("/api/v1/blocklist?sortKey=guid")
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "sortKey"


@pytest.mark.req("FRG-UI-017")
def test_delete_removes_and_unknown_is_404(client):
    db = client.app.state.db
    block_id = client.portal.call(lambda: _insert_block(db))

    resp = client.delete(f"/api/v1/blocklist/{block_id}")
    assert resp.status_code == 200
    assert resp.json() == {"id": block_id, "removed": True}
    assert client.get("/api/v1/blocklist").json()["totalRecords"] == 0

    assert client.delete(f"/api/v1/blocklist/{block_id}").status_code == 404
    assert client.delete("/api/v1/blocklist/9999").status_code == 404


@pytest.mark.req("FRG-UI-017")
def test_bulk_delete_reports_deleted_and_missing(client):
    db = client.app.state.db
    a = client.portal.call(lambda: _insert_block(db, guid="GA"))
    b = client.portal.call(lambda: _insert_block(db, guid="GB"))

    resp = client.post("/api/v1/blocklist/delete", json={"ids": [a, 9999, b]})
    assert resp.status_code == 200
    assert resp.json() == {"deleted": [a, b], "missing": [9999]}
    assert client.get("/api/v1/blocklist").json()["totalRecords"] == 0

    # Idempotent second call: nothing left to delete, everything reported.
    again = client.post("/api/v1/blocklist/delete", json={"ids": [a, b]})
    assert again.json() == {"deleted": [], "missing": [a, b]}


@pytest.mark.req("FRG-UI-017")
def test_removing_a_blocklist_row_makes_the_release_grabbable_again(client):
    """The decision-level promise: the search engine's blocklist spec rejects
    the release while the row exists, and approves the SAME candidate once the
    row is deleted through the API (the store is a per-search snapshot, so no
    cache invalidation is involved)."""
    from foragerr.releases import ReleaseCandidate
    from foragerr.search import DecisionEngine, EvaluationContext

    db = client.app.state.db
    block_id = client.portal.call(lambda: _insert_block(db, guid="G1"))

    candidate = ReleaseCandidate(
        guid="G1",
        title="Spawn 001 (2024)",
        link="https://idx.test/nzb/1",
        indexer_id=7,
        indexer_name="DogNZB",
        indexer_priority=10,
        query_tier=0,
        size_bytes=12345,
        pub_date=None,
        categories=(),
    )

    async def _load_store():
        async with db.read_session() as session:
            return await load_blocklist_store(session)

    engine = DecisionEngine()

    before = engine.evaluate(
        candidate, EvaluationContext(blocklist=client.portal.call(_load_store))
    )
    assert any(r.spec == "blocklist" for r in before.rejections)

    assert client.delete(f"/api/v1/blocklist/{block_id}").status_code == 200

    after = engine.evaluate(
        candidate, EvaluationContext(blocklist=client.portal.call(_load_store))
    )
    assert not any(r.spec == "blocklist" for r in after.rejections)
