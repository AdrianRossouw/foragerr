"""The ``creator-bibliography-fetch`` command (FRG-CRTR-005).

Drives the real fetch against a ``FakeCV`` double whose person-detail endpoint
serves volume-credit STUBS and whose ``volumes/?filter=id:...`` endpoint hydrates
full rows — mirroring the live shapes. Asserts the bounded, in-library-excluding,
newest-first cache; atomic replace + stamp; a failure that preserves the previous
cache; and that the fetch acquires nothing (no series/command/follow writes).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from foragerr.creators.bibliography import (
    BIBLIOGRAPHY_CAP,
    fetch_creator_bibliography,
)
from foragerr.creators.models import CreatorBibliographyRow, CreatorRow
from foragerr.db import CommandRow
from foragerr.db.base import utcnow
from foragerr.library import repo
from foragerr.metadata import ComicVineError
from foragerr.library.models import SeriesRow

from flows_support import FakeCV, build_factory


async def _make_creator(db, cv_person_id: int, *, followed: bool = False) -> int:
    async with db.write_session() as session:
        row = CreatorRow(
            cv_person_id=cv_person_id,
            name=f"Person {cv_person_id}",
            followed=followed,
            created_at=utcnow(),
        )
        session.add(row)
        await session.flush()
        return row.id


async def _make_series(db, root_folder_path: Path, format_profile_id: int, *, cv_volume_id: int) -> int:
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=cv_volume_id,
            title=f"Series {cv_volume_id}",
            monitored=True,
            monitor_new_items="all",
            format_profile_id=format_profile_id,
            root_folder_id=(await repo.list_root_folders(session))[0].id,
            path=str(root_folder_path / f"series-{cv_volume_id}"),
        )
        return series.id


async def _cached_volume_ids(db, creator_id: int) -> set[int]:
    async with db.read_session() as session:
        rows = (
            await session.execute(
                select(CreatorBibliographyRow.cv_volume_id).where(
                    CreatorBibliographyRow.creator_id == creator_id
                )
            )
        ).scalars().all()
    return set(rows)


async def _stamp(db, creator_id: int):
    async with db.read_session() as session:
        return await session.scalar(
            select(CreatorRow.bibliography_fetched_at).where(CreatorRow.id == creator_id)
        )


# --- FRG-CRTR-005 -----------------------------------------------------------


@pytest.mark.req("FRG-CRTR-005")
async def test_fetch_caps_excludes_in_library_and_keeps_newest(
    db, settings, root_folder_id, root_folder_path, format_profile_id
):
    creator_id = await _make_creator(db, cv_person_id=100)

    # 30 credited volumes (ids 1..30). start_year = 2000 + id, so higher id = newer.
    fake = FakeCV()
    for vid in range(1, 31):
        fake.volume(vid, name=f"Vol {vid}", start_year=2000 + vid, count_of_issues=vid)
    fake.person(100, volume_ids=list(range(1, 31)))

    # Two of them (ids 1, 2) are already in the library -> excluded at fetch.
    await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)
    await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=2)

    factory = build_factory(settings, fake.handler())
    summary = await fetch_creator_bibliography(db, settings, creator_id, factory=factory)

    cached = await _cached_volume_ids(db, creator_id)
    # Not-in-library set is ids 3..30 (28 volumes); the cap keeps the newest 24 by
    # start_year: ids 7..30. The in-library ids 1,2 never appear.
    assert cached == set(range(7, 31))
    assert len(cached) == BIBLIOGRAPHY_CAP
    assert 1 not in cached and 2 not in cached
    assert await _stamp(db, creator_id) is not None
    assert "24" in summary


@pytest.mark.req("FRG-CRTR-005")
async def test_fetch_replaces_previous_rows_and_stamps(
    db, settings, root_folder_id, root_folder_path, format_profile_id
):
    creator_id = await _make_creator(db, cv_person_id=100)

    # A stale cache row from a prior fetch that the new fetch must replace.
    async with db.write_session() as session:
        session.add(
            CreatorBibliographyRow(
                creator_id=creator_id, cv_volume_id=999, title="Old volume"
            )
        )

    fake = FakeCV()
    fake.volume(50, name="New A", start_year=2010)
    fake.volume(51, name="New B", start_year=2011)
    fake.person(100, volume_ids=[50, 51])

    factory = build_factory(settings, fake.handler())
    await fetch_creator_bibliography(db, settings, creator_id, factory=factory)

    cached = await _cached_volume_ids(db, creator_id)
    assert cached == {50, 51}  # the stale 999 row was replaced away
    assert await _stamp(db, creator_id) is not None


@pytest.mark.req("FRG-CRTR-005")
async def test_hydration_failure_preserves_cache_and_stamp(
    db, settings, root_folder_id, root_folder_path, format_profile_id
):
    creator_id = await _make_creator(db, cv_person_id=100)

    # Seed an existing cache + an explicit stamp the failed fetch must NOT touch.
    marker = utcnow()
    async with db.write_session() as session:
        creator = await session.get(CreatorRow, creator_id)
        creator.bibliography_fetched_at = marker
        session.add(
            CreatorBibliographyRow(
                creator_id=creator_id, cv_volume_id=777, title="Kept volume"
            )
        )

    fake = FakeCV()
    fake.volume(60, name="Candidate", start_year=2015)
    fake.person(100, volume_ids=[60])
    fake.fail_volumes_filter(500)  # hydration blows up mid-run

    factory = build_factory(settings, fake.handler())
    # The handler RAISES so the command framework records status=failed — the
    # WS bridge invalidates only COMPLETED fetches, so a broken ComicVine
    # cannot spin an invalidate→refetch→re-enqueue loop (gate finding).
    with pytest.raises(ComicVineError):
        await fetch_creator_bibliography(db, settings, creator_id, factory=factory)

    # The previous cache + stamp survive untouched.
    assert await _cached_volume_ids(db, creator_id) == {777}
    assert await _stamp(db, creator_id) == marker


@pytest.mark.req("FRG-CRTR-005")
async def test_person_fetch_failure_preserves_cache(
    db, settings, root_folder_id, root_folder_path, format_profile_id
):
    creator_id = await _make_creator(db, cv_person_id=100)
    async with db.write_session() as session:
        session.add(
            CreatorBibliographyRow(
                creator_id=creator_id, cv_volume_id=777, title="Kept"
            )
        )

    fake = FakeCV()
    fake.person(100, volume_ids=[60], fail_status=503)

    factory = build_factory(settings, fake.handler())
    with pytest.raises(ComicVineError):
        await fetch_creator_bibliography(db, settings, creator_id, factory=factory)

    assert await _cached_volume_ids(db, creator_id) == {777}
    assert await _stamp(db, creator_id) is None  # never advanced


@pytest.mark.req("FRG-CRTR-005")
async def test_fetch_acquires_nothing(
    db, settings, root_folder_id, root_folder_path, format_profile_id
):
    creator_id = await _make_creator(db, cv_person_id=100, followed=False)
    await _make_series(db, root_folder_path, format_profile_id, cv_volume_id=1)

    async def _counts():
        async with db.read_session() as session:
            series = await session.scalar(select(func.count()).select_from(SeriesRow))
            commands = await session.scalar(select(func.count()).select_from(CommandRow))
            followed = await session.scalar(
                select(CreatorRow.followed).where(CreatorRow.id == creator_id)
            )
        return series, commands, followed

    before = await _counts()

    fake = FakeCV()
    fake.volume(50, name="New A", start_year=2010)
    fake.person(100, volume_ids=[50])
    factory = build_factory(settings, fake.handler())
    await fetch_creator_bibliography(db, settings, creator_id, factory=factory)

    # No series created, no command enqueued, no follow flag changed — only the
    # bibliography cache + stamp were written.
    assert await _counts() == before


@pytest.mark.req("FRG-CRTR-005")
async def test_unknown_creator_is_recorded_noop(
    db, settings, root_folder_id, root_folder_path, format_profile_id
):
    fake = FakeCV()
    factory = build_factory(settings, fake.handler())
    summary = await fetch_creator_bibliography(db, settings, 999999, factory=factory)

    assert "no longer exists" in summary
    async with db.read_session() as session:
        total = await session.scalar(
            select(func.count()).select_from(CreatorBibliographyRow)
        )
    assert total == 0
