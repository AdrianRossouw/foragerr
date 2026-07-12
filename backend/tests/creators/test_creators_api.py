"""HTTP contract tests for the creators router (FRG-API-023, FRG-CRTR-004).

Exercises the grid list (aggregates, paging, sort, followed filter), the profile
aggregates (owned/total issue counts against ``issue_files``, publisher count),
and the follow toggle (flips + user-touches the flag, writes nothing else, 404s).
A dedicated test asserts that serving these routes constructs no ComicVine
client — every aggregate is a DB query (FRG-API-023: no ComicVine request).

Uses an ASGI-transport client driven on the current event loop (so seeding via
``app.state.db`` and HTTP calls share one loop), mirroring
``test_system_ops_api.py``.
"""

from __future__ import annotations

import datetime as dt
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from foragerr.app import create_app
from foragerr.creators.models import CreatorRow, IssueCreditRow
from foragerr.db.base import utcnow
from foragerr.library import repo
from foragerr.library.models import IssueRow
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

from http_support import make_settings


@asynccontextmanager
async def running_app(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(make_settings(cfg))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield app, client


async def _format_profile_id(app) -> int:
    async with app.state.db.read_session() as session:
        return await session.scalar(
            select(FormatProfileRow.id).where(FormatProfileRow.name == DEFAULT_PROFILE_NAME)
        )


async def _seed_library(app, tmp_path: Path) -> dict[str, int]:
    """Two series, three issues, two creators, credits, one owned file.

    Alice (cv 10): writer on S1#1, artist on S2#1  -> two distinct series.
      S1#1 owns a file; S2#1 does not.
    Bob (cv 11): penciler on S1#2 -> one series.
    """
    root = tmp_path / "root"
    root.mkdir()
    fpid = await _format_profile_id(app)
    ids: dict[str, int] = {}
    async with app.state.db.write_session() as session:
        rf = await repo.create_root_folder(session, str(root))
        s1 = await repo.create_series(
            session,
            cv_volume_id=1,
            title="Alpha",
            sort_title="Alpha",
            publisher="Image",
            format_profile_id=fpid,
            root_folder_id=rf.id,
            path=str(root / "alpha"),
        )
        s1.cover_cached_at = utcnow()  # S1 has a cached cover
        s2 = await repo.create_series(
            session,
            cv_volume_id=2,
            title="Beta",
            sort_title="Beta",
            publisher="DC",
            format_profile_id=fpid,
            root_folder_id=rf.id,
            path=str(root / "beta"),
        )
        # s2.cover_cached_at stays None -> coverAvailable False
        i1 = await repo.create_issue(session, series_id=s1.id, cv_issue_id=100, issue_number="1")
        i2 = await repo.create_issue(session, series_id=s1.id, cv_issue_id=101, issue_number="2")
        i3 = await repo.create_issue(session, series_id=s2.id, cv_issue_id=200, issue_number="1")
        await repo.add_issue_file(session, issue_id=i1.id, path=str(root / "alpha-1.cbz"), size=10)

        alice = CreatorRow(cv_person_id=10, name="Alice", followed=True, created_at=utcnow())
        bob = CreatorRow(cv_person_id=11, name="Bob", followed=False, created_at=utcnow())
        session.add_all([alice, bob])
        await session.flush()
        session.add_all(
            [
                IssueCreditRow(issue_id=i1.id, creator_id=alice.id, role_normalized="writer", role_verbatim="writer"),
                IssueCreditRow(issue_id=i3.id, creator_id=alice.id, role_normalized="artist", role_verbatim="artist"),
                IssueCreditRow(issue_id=i2.id, creator_id=bob.id, role_normalized="penciler", role_verbatim="penciler"),
            ]
        )
        ids.update(
            {"s1": s1.id, "s2": s2.id, "i1": i1.id, "i3": i3.id, "alice": alice.id, "bob": bob.id}
        )
    return ids


# --- FRG-API-023: grid list -------------------------------------------------


@pytest.mark.req("FRG-API-023")
async def test_list_carries_row_fields_and_header_aggregates(tmp_path):
    async with running_app(tmp_path) as (app, client):
        ids = await _seed_library(app, tmp_path)

        resp = await client.get("/api/v1/creators")
        assert resp.status_code == 200
        body = resp.json()

        # Paging envelope + grid-header aggregates.
        assert body["page"] == 1
        assert body["totalRecords"] == 2
        assert body["totalCreators"] == 2
        assert body["followedCreators"] == 1  # only Alice

        by_name = {r["name"]: r for r in body["records"]}
        alice = by_name["Alice"]
        assert alice["roles"] == ["artist", "writer"]  # sorted normalized set
        assert alice["seriesCount"] == 2
        assert alice["followed"] is True
        works = {w["seriesId"]: w for w in alice["works"]}
        assert works[ids["s1"]]["coverAvailable"] is True
        assert works[ids["s2"]]["coverAvailable"] is False
        assert {w["title"] for w in alice["works"]} == {"Alpha", "Beta"}

        assert by_name["Bob"]["seriesCount"] == 1
        assert by_name["Bob"]["followed"] is False


@pytest.mark.req("FRG-API-023")
async def test_list_paging_sort_and_followed_filter(tmp_path):
    async with running_app(tmp_path) as (app, client):
        await _seed_library(app, tmp_path)

        # seriesCount desc -> Alice (2) before Bob (1).
        resp = await client.get("/api/v1/creators?sortKey=seriesCount&sortDirection=desc")
        names = [r["name"] for r in resp.json()["records"]]
        assert names == ["Alice", "Bob"]

        # name asc is the default order.
        resp = await client.get("/api/v1/creators?sortKey=name&sortDirection=asc")
        assert [r["name"] for r in resp.json()["records"]] == ["Alice", "Bob"]

        # Paging: pageSize 1 windows the sorted set; aggregates stay whole-library.
        page1 = (await client.get("/api/v1/creators?pageSize=1&page=1")).json()
        page2 = (await client.get("/api/v1/creators?pageSize=1&page=2")).json()
        assert len(page1["records"]) == 1 and len(page2["records"]) == 1
        assert page1["totalRecords"] == 2 and page1["totalCreators"] == 2
        assert {page1["records"][0]["name"], page2["records"][0]["name"]} == {"Alice", "Bob"}

        # followed=true filters rows but leaves the header aggregates unchanged.
        filtered = (await client.get("/api/v1/creators?followed=true")).json()
        assert [r["name"] for r in filtered["records"]] == ["Alice"]
        assert filtered["totalRecords"] == 1
        assert filtered["totalCreators"] == 2 and filtered["followedCreators"] == 1

        # An unknown sortKey is a 400 in the uniform error shape naming the field.
        bad = await client.get("/api/v1/creators?sortKey=bogus")
        assert bad.status_code == 400
        assert bad.json()["errors"][0]["field"] == "sortKey"


# --- FRG-API-023: seriesId focus filter (FRG-UI-027 focus chip) -------------


@pytest.mark.req("FRG-API-023")
async def test_series_filter_returns_only_credited_creators(tmp_path):
    async with running_app(tmp_path) as (app, client):
        ids = await _seed_library(app, tmp_path)

        # S1 credits Alice (writer) + Bob (penciler); S2 credits only Alice.
        s1 = (await client.get(f"/api/v1/creators?seriesId={ids['s1']}")).json()
        assert {r["name"] for r in s1["records"]} == {"Alice", "Bob"}
        assert s1["totalRecords"] == 2
        # Header aggregates stay GLOBAL regardless of the focus (FRG-UI-027).
        assert s1["totalCreators"] == 2 and s1["followedCreators"] == 1

        s2 = (await client.get(f"/api/v1/creators?seriesId={ids['s2']}")).json()
        assert {r["name"] for r in s2["records"]} == {"Alice"}
        assert s2["totalRecords"] == 1
        assert s2["totalCreators"] == 2 and s2["followedCreators"] == 1


@pytest.mark.req("FRG-API-023")
async def test_series_filter_composes_with_followed_and_paging(tmp_path):
    async with running_app(tmp_path) as (app, client):
        ids = await _seed_library(app, tmp_path)

        # seriesId + followed: S1 credits Alice + Bob, but only Alice is followed.
        both = (
            await client.get(
                f"/api/v1/creators?seriesId={ids['s1']}&followed=true"
            )
        ).json()
        assert [r["name"] for r in both["records"]] == ["Alice"]
        assert both["totalRecords"] == 1
        assert both["totalCreators"] == 2 and both["followedCreators"] == 1

        # seriesId + paging: the two S1 creators window across two pages.
        p1 = (
            await client.get(f"/api/v1/creators?seriesId={ids['s1']}&pageSize=1&page=1")
        ).json()
        p2 = (
            await client.get(f"/api/v1/creators?seriesId={ids['s1']}&pageSize=1&page=2")
        ).json()
        assert len(p1["records"]) == 1 and len(p2["records"]) == 1
        assert p1["totalRecords"] == 2
        assert {p1["records"][0]["name"], p2["records"][0]["name"]} == {"Alice", "Bob"}


@pytest.mark.req("FRG-API-023")
async def test_unknown_series_filter_is_empty_with_global_aggregates(tmp_path):
    async with running_app(tmp_path) as (app, client):
        await _seed_library(app, tmp_path)

        body = (await client.get("/api/v1/creators?seriesId=999999")).json()
        assert body["records"] == []
        assert body["totalRecords"] == 0
        # The header count line remains the whole-library aggregate (FRG-UI-027).
        assert body["totalCreators"] == 2 and body["followedCreators"] == 1


@pytest.mark.req("FRG-API-023")
async def test_invalid_series_filter_is_rejected(tmp_path):
    async with running_app(tmp_path) as (app, client):
        await _seed_library(app, tmp_path)

        # seriesId is validated ge=1. The house contract maps every
        # RequestValidationError (query/path/body) to a uniform 400 (see
        # api.errors._validation_exception_handler) rather than FastAPI's default
        # 422, so a non-positive / non-integer value is a 400.
        assert (await client.get("/api/v1/creators?seriesId=0")).status_code == 400
        assert (await client.get("/api/v1/creators?seriesId=-3")).status_code == 400
        assert (
            await client.get("/api/v1/creators?seriesId=notanint")
        ).status_code == 400


# --- FRG-API-023: profile ----------------------------------------------------


@pytest.mark.req("FRG-API-023")
async def test_profile_aggregates_match_seeded_credits(tmp_path):
    async with running_app(tmp_path) as (app, client):
        ids = await _seed_library(app, tmp_path)

        # Grow S1 into a whole-series scenario: Alice is credited on only 1 issue
        # of the series (i1, writer), but the profile's owned/total counts are
        # WHOLE-SERIES (FRG-API-023: "owned/total issue counts across those
        # series") = the series' own progress. Bring S1 to 12 issues total and
        # 6 owned (i1 already owns a file; add 5 more owned + the rest unowned).
        root = tmp_path / "root"
        async with app.state.db.write_session() as session:
            for n in range(3, 13):  # issues #3..#12 -> S1 now has 12 issues
                iss = await repo.create_issue(
                    session, series_id=ids["s1"], cv_issue_id=100 + n, issue_number=str(n)
                )
                if n <= 7:  # 5 of the new issues own a file (i1 + 5 = 6 owned)
                    await repo.add_issue_file(
                        session, issue_id=iss.id, path=str(root / f"alpha-{n}.cbz"), size=10
                    )

        resp = await client.get(f"/api/v1/creators/{ids['alice']}")
        assert resp.status_code == 200
        body = resp.json()

        assert body["name"] == "Alice"
        assert body["roles"] == ["artist", "writer"]
        assert body["followed"] is True

        stats = body["stats"]
        assert stats["seriesCount"] == 2
        # Whole-series sums: S1 (12) + S2 (1) total; S1 (6) + S2 (0) owned.
        assert stats["totalIssues"] == 13
        assert stats["ownedIssues"] == 6
        assert stats["publisherCount"] == 2  # Image + DC

        by_series = {s["seriesId"]: s for s in body["series"]}
        s1 = by_series[ids["s1"]]
        assert s1["publisher"] == "Image"
        assert s1["roles"] == ["writer"]  # credited on 1 of the 12 issues
        # ...but counts are the whole series: 6 owned of 12 total.
        assert (s1["totalIssues"], s1["ownedIssues"]) == (12, 6)
        s2 = by_series[ids["s2"]]
        assert s2["roles"] == ["artist"]
        assert (s2["totalIssues"], s2["ownedIssues"]) == (1, 0)


@pytest.mark.req("FRG-API-023")
async def test_profile_unknown_id_is_404(tmp_path):
    async with running_app(tmp_path) as (app, client):
        resp = await client.get("/api/v1/creators/9999")
        assert resp.status_code == 404
        assert "message" in resp.json()


# --- FRG-API-023 / FRG-CRTR-004: follow toggle ------------------------------


@pytest.mark.req("FRG-CRTR-004")
async def test_follow_toggle_flips_touches_and_no_side_effects(tmp_path):
    async with running_app(tmp_path) as (app, client):
        ids = await _seed_library(app, tmp_path)

        # Snapshot the state the toggle must NOT touch (series/issue/file rows).
        async def _snapshot():
            async with app.state.db.read_session() as session:
                from foragerr.library.models import IssueFileRow, SeriesRow

                series = {
                    r.id: (r.monitored, r.title)
                    for r in (await session.execute(select(SeriesRow))).scalars().all()
                }
                issues = {
                    r.id: r.monitored
                    for r in (await session.execute(select(IssueRow))).scalars().all()
                }
                files = {
                    r.id for r in (await session.execute(select(IssueFileRow))).scalars().all()
                }
                return series, issues, files

        before = await _snapshot()

        # Unfollow the seeded creator (Alice).
        resp = await client.put(
            f"/api/v1/creators/{ids['alice']}/follow", json={"followed": False}
        )
        assert resp.status_code == 200
        row = resp.json()
        assert row["id"] == ids["alice"]
        assert row["followed"] is False
        # The updated row still carries the full grid fields.
        assert row["seriesCount"] == 2 and row["roles"] == ["artist", "writer"]

        # The flag flipped AND is now user-touched (FRG-CRTR-004).
        async with app.state.db.read_session() as session:
            alice = await session.get(CreatorRow, ids["alice"])
            assert alice.followed is False
            assert alice.follow_touched is not None

        # No series/issue/file state changed anywhere.
        assert await _snapshot() == before

        # Re-follow round-trips through the same endpoint.
        resp = await client.put(
            f"/api/v1/creators/{ids['alice']}/follow", json={"followed": True}
        )
        assert resp.json()["followed"] is True


@pytest.mark.req("FRG-API-023")
async def test_follow_toggle_unknown_id_is_404(tmp_path):
    async with running_app(tmp_path) as (app, client):
        resp = await client.put("/api/v1/creators/9999/follow", json={"followed": True})
        assert resp.status_code == 404


# --- FRG-API-023: no ComicVine request served from these routes -------------


@pytest.mark.req("FRG-API-023")
async def test_routes_construct_no_comicvine_client(tmp_path, monkeypatch):
    async with running_app(tmp_path) as (app, client):
        ids = await _seed_library(app, tmp_path)

        # Any attempt to construct a ComicVine client while serving these routes
        # is a hard failure — the aggregates are pure DB reads (FRG-API-023).
        import foragerr.metadata as metadata

        class _NoCV:
            def __init__(self, *args, **kwargs):
                raise AssertionError("creators routes must not construct a ComicVine client")

        monkeypatch.setattr(metadata, "ComicVineClient", _NoCV)

        assert (await client.get("/api/v1/creators")).status_code == 200
        assert (await client.get(f"/api/v1/creators/{ids['alice']}")).status_code == 200
        assert (
            await client.put(
                f"/api/v1/creators/{ids['alice']}/follow", json={"followed": False}
            )
        ).status_code == 200
