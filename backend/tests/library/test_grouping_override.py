"""Grouping manual override survives refresh (FRG-SER-017).

The operator can reassign a series to a different franchise group, detach it,
rename a group, or clear the lock — and reassign/detach LOCK the series so a
later ``refresh-series`` never re-derives over the choice (mirroring the
``aliases`` user-override precedent). An emptied group is pruned.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.commands import CommandService
from foragerr.library import repo
from foragerr.library.flows import (
    GroupEdit,
    SeriesValidationError,
    add_series,
    edit_series,
    refresh_series,
)
from foragerr.library.models import SeriesGroupRow

from flows_support import FakeCV, build_factory, flows_settings, issue


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return flows_settings(cfg)


@pytest.fixture
async def commands(db, settings, command_registry):
    return CommandService(db, settings)


async def _add(db, settings, commands, root_folder_id, *, cv_volume_id, name):
    factory = build_factory(settings, FakeCV().volume(cv_volume_id, name=name).handler())
    result = await add_series(
        db,
        settings,
        cv_volume_id=cv_volume_id,
        root_folder_id=root_folder_id,
        commands=commands,
        enqueue_refresh=False,
        factory=factory,
    )
    return result.series.id


async def _refresh(db, settings, commands, sid, name):
    # The FakeCV volume id must match the series' own cv_volume_id (refresh
    # fetches by it), so resolve it rather than assuming it equals the series id.
    async with db.read_session() as session:
        cv_id = (await repo.get_series(session, sid)).cv_volume_id
    factory = build_factory(
        settings,
        FakeCV().volume(cv_id, name=name).issues(cv_id, [issue(cv_id * 10, "1")]).handler(),
    )
    await refresh_series(db, settings, sid, commands=commands, factory=factory)


@pytest.mark.req("FRG-SER-017")
async def test_reassigned_series_survives_refresh_and_empties_group_is_pruned(
    db, settings, commands, root_folder_id, format_profile_id
):
    a = await _add(db, settings, commands, root_folder_id, cv_volume_id=1, name="Batman (2011)")
    b = await _add(db, settings, commands, root_folder_id, cv_volume_id=2, name="Superman (2011)")

    async with db.read_session() as session:
        batman_group = (await repo.get_series(session, a)).series_group_id
        superman_group = (await repo.get_series(session, b)).series_group_id
    assert batman_group != superman_group

    # Reassign A into Superman's group; A is now locked and Batman's group is
    # empty -> pruned.
    await edit_series(
        db, a, group_op=GroupEdit(action="reassign", series_group_id=superman_group)
    )
    async with db.read_session() as session:
        sa = await repo.get_series(session, a)
        assert sa.series_group_id == superman_group
        assert sa.group_locked is True
        remaining = (await session.execute(select(SeriesGroupRow.id))).scalars().all()
    assert batman_group not in remaining  # emptied group pruned

    # A later refresh must NOT re-derive over the operator's locked choice.
    await _refresh(db, settings, commands, a, "Batman (2011)")
    async with db.read_session() as session:
        sa = await repo.get_series(session, a)
    assert sa.series_group_id == superman_group
    assert sa.group_locked is True


@pytest.mark.req("FRG-SER-017")
async def test_detach_locks_series_ungrouped(
    db, settings, commands, root_folder_id, format_profile_id
):
    a = await _add(db, settings, commands, root_folder_id, cv_volume_id=5, name="Hellboy (1994)")
    await edit_series(db, a, group_op=GroupEdit(action="detach"))

    async with db.read_session() as session:
        sa = await repo.get_series(session, a)
    assert sa.series_group_id is None
    assert sa.group_locked is True

    await _refresh(db, settings, commands, a, "Hellboy (1994)")
    async with db.read_session() as session:
        sa = await repo.get_series(session, a)
    assert sa.series_group_id is None  # stays detached (locked)


@pytest.mark.req("FRG-SER-017")
async def test_group_rename_persists_across_refresh(
    db, settings, commands, root_folder_id, format_profile_id
):
    a = await _add(db, settings, commands, root_folder_id, cv_volume_id=3, name="Saga (2012)")
    await edit_series(
        db, a, group_op=GroupEdit(action="rename", title="Saga Franchise")
    )

    async with db.read_session() as session:
        sa = await repo.get_series(session, a)
        group = await session.get(SeriesGroupRow, sa.series_group_id)
        assert group.title == "Saga Franchise"
        assert group.manual_title is True

    await _refresh(db, settings, commands, a, "Saga (2012)")
    async with db.read_session() as session:
        sa = await repo.get_series(session, a)
        group = await session.get(SeriesGroupRow, sa.series_group_id)
    assert group.title == "Saga Franchise"  # rename survives, group kept its member


@pytest.mark.req("FRG-SER-017")
async def test_clearing_the_lock_re_derives_on_next_refresh(
    db, settings, commands, root_folder_id, format_profile_id
):
    a = await _add(db, settings, commands, root_folder_id, cv_volume_id=1, name="Batman (2011)")
    b = await _add(db, settings, commands, root_folder_id, cv_volume_id=2, name="Superman (2011)")
    async with db.read_session() as session:
        superman_group = (await repo.get_series(session, b)).series_group_id

    # Reassign A into Superman's group (locked), then clear the lock.
    await edit_series(
        db, a, group_op=GroupEdit(action="reassign", series_group_id=superman_group)
    )
    await edit_series(db, a, group_op=GroupEdit(action="unlock"))
    async with db.read_session() as session:
        sa = await repo.get_series(session, a)
        assert sa.group_locked is False
        assert sa.series_group_id == superman_group  # unlock alone doesn't move it

    # Next refresh re-derives: A returns to its own franchise ("batman").
    await _refresh(db, settings, commands, a, "Batman (2011)")
    async with db.read_session() as session:
        sa = await repo.get_series(session, a)
        group = await session.get(SeriesGroupRow, sa.series_group_id)
    assert sa.series_group_id != superman_group
    assert group.grouping_key == "batman"


@pytest.mark.req("FRG-SER-017")
async def test_reassign_to_unknown_group_is_rejected(
    db, settings, commands, root_folder_id, format_profile_id
):
    a = await _add(db, settings, commands, root_folder_id, cv_volume_id=9, name="Spawn (1992)")
    with pytest.raises(SeriesValidationError):
        await edit_series(
            db, a, group_op=GroupEdit(action="reassign", series_group_id=999999)
        )
