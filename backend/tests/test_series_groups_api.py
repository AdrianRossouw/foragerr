"""HTTP contract tests for the series grouping projection (FRG-API-020).

``GET /api/v1/series/groups`` returns franchise groups (each with member series
and an AGGREGATED roll-up) plus ungrouped series as singleton franchises, in
the standard paging envelope, with no secret exposed. The flat ``GET /series``
resource additionally carries its ``series_group_id``. The roll-up is computed
by a single bounded aggregate query, never the per-series statistics N+1.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flows_support import flows_settings
from foragerr.app import create_app
from foragerr.library import repo


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


async def _seed_franchises(app, root: Path) -> None:
    """Three series across two franchises: Batman (2011)+(2016) fold to one
    group, Superman (2011) is its own. Issues/files chosen so the aggregated
    roll-up has distinct, checkable numbers."""
    db = app.state.db
    async with db.write_session() as session:
        root_row = await repo.create_root_folder(session, str(root))
        from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow
        from sqlalchemy import select

        profile_id = await session.scalar(
            select(FormatProfileRow.id).where(FormatProfileRow.name == DEFAULT_PROFILE_NAME)
        )

        async def make(cv_id, title, path, issues_files):
            series = await repo.create_series(
                session,
                cv_volume_id=cv_id,
                title=title,
                format_profile_id=profile_id,
                root_folder_id=root_row.id,
                path=path,
            )
            await repo.apply_autogrouping(session, series)
            for n, (cv_issue, has_file) in enumerate(issues_files, start=1):
                iss = await repo.create_issue(
                    session,
                    series_id=series.id,
                    cv_issue_id=cv_issue,
                    issue_number=str(n),
                    cover_date=dt.date(2011, 1, n),
                )
                if has_file:
                    await repo.add_issue_file(
                        session, issue_id=iss.id, path=f"{path}/{cv_issue}.cbz", size=10
                    )

        # Batman group: 2 series, 2+1=3 issues, 1 owned.
        await make(1, "Batman (2011)", "/lib/Batman (2011)", [(100, True), (101, False)])
        await make(2, "Batman (2016)", "/lib/Batman (2016)", [(102, False)])
        # Superman group: 1 series, 3 issues, 2 owned.
        await make(
            3, "Superman (2011)", "/lib/Superman (2011)", [(200, True), (201, True), (202, False)]
        )


@pytest.mark.req("FRG-API-020")
def test_series_groups_returns_franchises_with_aggregated_stats(client, tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    client.portal.call(_seed_franchises, client.app, root)

    response = client.get("/api/v1/series/groups", params={"pageSize": 50})
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
    assert body["totalRecords"] == 2  # two franchises
    by_title = {rec["title"]: rec for rec in body["records"]}
    assert set(by_title) == {"Batman", "Superman"}

    batman = by_title["Batman"]
    assert batman["kind"] == "group"
    assert batman["series_count"] == 2
    assert batman["issue_count"] == 3
    assert batman["owned_count"] == 1
    assert {m["title"] for m in batman["series"]} == {"Batman (2011)", "Batman (2016)"}

    superman = by_title["Superman"]
    assert superman["series_count"] == 1
    assert superman["issue_count"] == 3
    assert superman["owned_count"] == 2
    assert len(superman["series"]) == 1

    # No secret material anywhere in the projection.
    assert "CV-SECRET-KEY" not in response.text


@pytest.mark.req("FRG-API-020")
def test_ungrouped_series_is_returned_as_a_singleton_franchise(client, tmp_path):
    root = tmp_path / "lib"
    root.mkdir()

    async def _seed(app):
        db = app.state.db
        from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow
        from sqlalchemy import select

        async with db.write_session() as session:
            root_row = await repo.create_root_folder(session, str(root))
            profile_id = await session.scalar(
                select(FormatProfileRow.id).where(
                    FormatProfileRow.name == DEFAULT_PROFILE_NAME
                )
            )
            series = await repo.create_series(
                session,
                cv_volume_id=42,
                title="(2011)",  # empty franchise key -> ungrouped
                format_profile_id=profile_id,
                root_folder_id=root_row.id,
                path="/lib/weird",
            )
            await repo.apply_autogrouping(session, series)
            await repo.create_issue(
                session, series_id=series.id, cv_issue_id=1, issue_number="1"
            )

    client.portal.call(_seed, client.app)
    response = client.get("/api/v1/series/groups")
    assert response.status_code == 200
    body = response.json()
    assert body["totalRecords"] == 1
    rec = body["records"][0]
    assert rec["kind"] == "series"
    assert rec["id"] is None
    assert rec["series_count"] == 1
    assert rec["issue_count"] == 1
    assert len(rec["series"]) == 1
    assert rec["series"][0]["series_group_id"] is None


@pytest.mark.req("FRG-API-020")
def test_group_rollup_does_not_double_count_multi_file_issue(client, tmp_path):
    """An issue with MORE THAN ONE issue_files row must count exactly once in
    both issue_count and owned_count — the EXISTS-based owned guard (and the
    distinct issue-id count) must not fan out over the files."""
    root = tmp_path / "lib"
    root.mkdir()

    async def _seed(app):
        db = app.state.db
        from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow
        from sqlalchemy import select

        async with db.write_session() as session:
            root_row = await repo.create_root_folder(session, str(root))
            profile_id = await session.scalar(
                select(FormatProfileRow.id).where(
                    FormatProfileRow.name == DEFAULT_PROFILE_NAME
                )
            )
            series = await repo.create_series(
                session,
                cv_volume_id=1,
                title="Batman (2011)",
                format_profile_id=profile_id,
                root_folder_id=root_row.id,
                path="/lib/Batman (2011)",
            )
            await repo.apply_autogrouping(session, series)
            iss = await repo.create_issue(
                session, series_id=series.id, cv_issue_id=100, issue_number="1"
            )
            # TWO files on the SAME issue (e.g. a dupe left before dedupe).
            await repo.add_issue_file(
                session, issue_id=iss.id, path="/lib/Batman (2011)/1a.cbz", size=10
            )
            await repo.add_issue_file(
                session, issue_id=iss.id, path="/lib/Batman (2011)/1b.cbz", size=10
            )

    async def _rollup(app):
        db = app.state.db
        async with db.read_session() as session:
            return await repo.series_group_rollup(session)

    client.portal.call(_seed, client.app)
    rollups = client.portal.call(_rollup, client.app)
    assert len(rollups) == 1
    batman = rollups[0]
    assert batman.series_count == 1
    assert batman.issue_count == 1  # one issue, not two (one per file)
    assert batman.owned_count == 1  # counted once despite two files


@pytest.mark.req("FRG-API-020")
def test_series_groups_unknown_sort_key_is_400(client):
    response = client.get("/api/v1/series/groups", params={"sortKey": "bogus"})
    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "sortKey"


@pytest.mark.req("FRG-API-020")
def test_flat_series_list_carries_series_group_id(client, tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    client.portal.call(_seed_franchises, client.app, root)

    response = client.get("/api/v1/series", params={"pageSize": 50})
    assert response.status_code == 200
    records = response.json()["records"]
    assert records  # sanity
    for rec in records:
        assert "series_group_id" in rec
        assert rec["series_group_id"] is not None  # all three seeded series grouped


@pytest.mark.req("FRG-API-020")
def test_group_rollup_is_a_single_bounded_query(client, tmp_path):
    """The roll-up aggregation is ONE SQL statement regardless of how many
    issues each member series has (no per-series statistics N+1)."""
    root = tmp_path / "lib"
    root.mkdir()
    client.portal.call(_seed_franchises, client.app, root)

    async def _count(app) -> tuple[int, list]:
        from sqlalchemy import event

        db = app.state.db
        statements: list[str] = []

        def _before(conn, cursor, statement, *args):
            statements.append(statement)

        sync_engine = db.engine.sync_engine
        event.listen(sync_engine, "before_cursor_execute", _before)
        try:
            async with db.read_session() as session:
                rollups = await repo.series_group_rollup(session)
        finally:
            event.remove(sync_engine, "before_cursor_execute", _before)
        return len(statements), rollups

    count, rollups = client.portal.call(_count, client.app)
    assert count == 1  # exactly one aggregate query for ALL groups
    assert len(rollups) == 2
