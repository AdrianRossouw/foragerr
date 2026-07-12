"""HTTP contract tests for the creator bibliography resource (FRG-API-024).

Exercises ``GET /api/v1/creators/{id}/bibliography``: a cold cache reports
``pending`` and enqueues exactly one deduplicated fetch, a fresh cache serves the
cached rows with ``state: fresh`` and no enqueue, a stale cache serves the rows
while enqueueing a refresh, the live in-library anti-join hides a volume added
after caching, an unknown id is a 404, and the handler constructs no ComicVine
client (the fetch rides the command backbone).

The command worker pool is drained immediately after startup so an enqueued
``creator-bibliography-fetch`` is never CONSUMED during a test — the real
service's queued/started dedup still applies, keeping the "exactly one command"
assertions deterministic without a worker racing to run (and network) the fetch.
"""

from __future__ import annotations

import datetime as dt
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from foragerr.app import create_app
from foragerr.creators.models import CreatorBibliographyRow, CreatorRow
from foragerr.db import CommandRow
from foragerr.db.base import utcnow
from foragerr.library import repo
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

from http_support import make_settings

_FETCH = "creator-bibliography-fetch"


@asynccontextmanager
async def running_app(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(make_settings(cfg))
    async with app.router.lifespan_context(app):
        # Stop the worker pool so an enqueued fetch is never consumed mid-test.
        await app.state.commands.drain(0.0)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield app, client


async def _make_creator(app, cv_person_id: int = 100) -> int:
    async with app.state.db.write_session() as session:
        row = CreatorRow(
            cv_person_id=cv_person_id,
            name=f"Person {cv_person_id}",
            followed=False,
            created_at=utcnow(),
        )
        session.add(row)
        await session.flush()
        return row.id


async def _seed_cache(app, creator_id: int, entries: list[dict], *, stamp) -> None:
    async with app.state.db.write_session() as session:
        creator = await session.get(CreatorRow, creator_id)
        creator.bibliography_fetched_at = stamp
        for e in entries:
            session.add(CreatorBibliographyRow(creator_id=creator_id, **e))


async def _add_library_series(app, tmp_path: Path, *, cv_volume_id: int) -> None:
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    async with app.state.db.read_session() as session:
        fpid = await session.scalar(
            select(FormatProfileRow.id).where(FormatProfileRow.name == DEFAULT_PROFILE_NAME)
        )
    async with app.state.db.write_session() as session:
        rf = await repo.create_root_folder(session, str(root))
        await repo.create_series(
            session,
            cv_volume_id=cv_volume_id,
            title=f"Series {cv_volume_id}",
            monitored=True,
            monitor_new_items="all",
            format_profile_id=fpid,
            root_folder_id=rf.id,
            path=str(root / f"series-{cv_volume_id}"),
        )


async def _fetch_command_count(app, creator_id: int) -> int:
    async with app.state.db.read_session() as session:
        return int(
            await session.scalar(
                select(func.count()).select_from(CommandRow).where(CommandRow.name == _FETCH)
            )
            or 0
        )


# --- FRG-API-024 ------------------------------------------------------------


@pytest.mark.req("FRG-API-024")
async def test_cold_cache_reports_pending_and_enqueues_once(tmp_path):
    async with running_app(tmp_path) as (app, client):
        creator_id = await _make_creator(app)

        resp = await client.get(f"/api/v1/creators/{creator_id}/bibliography")
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "pending"
        assert body["records"] == []
        assert await _fetch_command_count(app, creator_id) == 1

        # A second view dedups onto the still-queued fetch (FRG-SCHED-003).
        again = await client.get(f"/api/v1/creators/{creator_id}/bibliography")
        assert again.json()["state"] == "pending"
        assert await _fetch_command_count(app, creator_id) == 1


@pytest.mark.req("FRG-API-024")
async def test_fresh_cache_serves_without_enqueue(tmp_path):
    async with running_app(tmp_path) as (app, client):
        creator_id = await _make_creator(app)
        await _seed_cache(
            app,
            creator_id,
            [
                {"cv_volume_id": 11, "title": "Newer", "publisher": "Vertigo", "start_year": 2011, "count_of_issues": 20},
                {"cv_volume_id": 10, "title": "Older", "publisher": "Vertigo", "start_year": 2002, "count_of_issues": 150},
            ],
            stamp=utcnow(),
        )

        resp = await client.get(f"/api/v1/creators/{creator_id}/bibliography")
        body = resp.json()
        assert body["state"] == "fresh"
        # Newest-start_year-first ordering.
        assert [r["cvVolumeId"] for r in body["records"]] == [11, 10]
        first = body["records"][0]
        assert first["title"] == "Newer"
        assert first["publisher"] == "Vertigo"
        assert first["startYear"] == 2011
        assert first["countOfIssues"] == 20
        # Fresh -> no fetch enqueued.
        assert await _fetch_command_count(app, creator_id) == 0


@pytest.mark.req("FRG-API-024")
async def test_stale_cache_serves_rows_and_enqueues(tmp_path):
    async with running_app(tmp_path) as (app, client):
        creator_id = await _make_creator(app)
        stale = utcnow() - dt.timedelta(days=8)  # older than the 7d TTL
        await _seed_cache(
            app,
            creator_id,
            [{"cv_volume_id": 10, "title": "Stale but served", "publisher": None, "start_year": 2002, "count_of_issues": None}],
            stamp=stale,
        )

        resp = await client.get(f"/api/v1/creators/{creator_id}/bibliography")
        body = resp.json()
        assert body["state"] == "pending"  # a refresh is in flight
        assert [r["cvVolumeId"] for r in body["records"]] == [10]  # rows still served
        assert await _fetch_command_count(app, creator_id) == 1


@pytest.mark.req("FRG-API-024")
async def test_live_anti_join_hides_series_added_after_caching(tmp_path):
    async with running_app(tmp_path) as (app, client):
        creator_id = await _make_creator(app)
        await _seed_cache(
            app,
            creator_id,
            [
                {"cv_volume_id": 10, "title": "A", "publisher": None, "start_year": 2002, "count_of_issues": None},
                {"cv_volume_id": 11, "title": "B", "publisher": None, "start_year": 2011, "count_of_issues": None},
            ],
            stamp=utcnow(),
        )

        # Volume 10 is added to the library AFTER caching -> hidden without refetch.
        await _add_library_series(app, tmp_path, cv_volume_id=10)

        body = (await client.get(f"/api/v1/creators/{creator_id}/bibliography")).json()
        assert [r["cvVolumeId"] for r in body["records"]] == [11]
        assert body["state"] == "fresh"


@pytest.mark.req("FRG-API-024")
async def test_unknown_creator_is_404(tmp_path):
    async with running_app(tmp_path) as (app, client):
        resp = await client.get("/api/v1/creators/9999/bibliography")
        assert resp.status_code == 404


@pytest.mark.req("FRG-API-024")
async def test_handler_constructs_no_comicvine_client(tmp_path, monkeypatch):
    async with running_app(tmp_path) as (app, client):
        creator_id = await _make_creator(app)

        import foragerr.metadata as metadata

        class _NoCV:
            def __init__(self, *args, **kwargs):
                raise AssertionError(
                    "bibliography handler must not construct a ComicVine client"
                )

        monkeypatch.setattr(metadata, "ComicVineClient", _NoCV)

        resp = await client.get(f"/api/v1/creators/{creator_id}/bibliography")
        assert resp.status_code == 200
        assert resp.json()["state"] == "pending"
