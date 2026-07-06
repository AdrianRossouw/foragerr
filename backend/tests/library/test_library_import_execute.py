"""library-import execute: bulk add + shared-pipeline import (FRG-IMP-023).

Drives the staged groups end-to-end: confirm/override -> execute ->
``add_series`` (path_override in in-place mode) -> issue refresh -> the ONE
``import_candidate`` pipeline -> staging state transitions. The
``library_import_mode`` placement seam is pinned in both modes.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from flows_support import FakeCV, build_factory, flows_settings, issue
from foragerr.commands import CommandService
from foragerr.library.flows.library_import import (
    execute_library_import,
    scan_library_root,
)
from foragerr.library.models import (
    IssueFileRow,
    IssueRow,
    LibraryImportGroupRow,
    SeriesRow,
)

_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f9f0000000049454e44ae42"
    "6082"
)


def make_large_cbz(path: Path, *, filler: int = 200 * 1024) -> Path:
    """A valid cbz (>=1 image entry) clearing the 100 KiB junk floor."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("page000.png", _PNG_1x1)
        zf.writestr("filler.bin", os.urandom(filler))
    return path


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return flows_settings(cfg)


async def _confirm(db, group_id: int, cv_volume_id: int) -> None:
    async with db.write_session() as session:
        group = await session.get(LibraryImportGroupRow, group_id)
        group.state = "confirmed"
        group.confirmed_cv_volume_id = cv_volume_id


async def _groups_by_key(db, root_folder_id: int) -> dict[str, LibraryImportGroupRow]:
    async with db.read_session() as session:
        rows = (
            (
                await session.execute(
                    select(LibraryImportGroupRow).where(
                        LibraryImportGroupRow.root_folder_id == root_folder_id
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return {row.matching_key: row for row in rows}


async def _issue_file_paths(db, cv_volume_id: int) -> list[str]:
    async with db.read_session() as session:
        rows = (
            (
                await session.execute(
                    select(IssueFileRow.path)
                    .join(IssueRow, IssueFileRow.issue_id == IssueRow.id)
                    .join(SeriesRow, IssueRow.series_id == SeriesRow.id)
                    .where(SeriesRow.cv_volume_id == cv_volume_id)
                )
            )
            .scalars()
            .all()
        )
    return list(rows)


@pytest.mark.req("FRG-IMP-023")
async def test_mass_import_with_override_and_deselect(
    db, settings, root_folder_id, root_folder_path
):
    """Confirmed groups create their series and import through the shared
    pipeline; an overridden group uses the corrected volume even though the
    filenames parse to a different series title; a deselected group stays
    staged untouched."""
    make_large_cbz(root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz")
    # Files parse to "sagga" but the user corrects the match to Paper Girls:
    # the override must win over the disagreeing filename parse.
    overridden = make_large_cbz(
        root_folder_path / "Sagg Whatever" / "Sagga 001 (2015).cbz"
    )
    make_large_cbz(root_folder_path / "Descender" / "Descender 001 (2015).cbz")

    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .volume(202, name="Paper Girls", start_year=2015)
        .volume(303, name="Descender", start_year=2015)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
        .issues(202, [issue(9202, "1", cover_date="2015-10-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)

    await scan_library_root(db, settings, root_folder_id, factory=factory)
    groups = await _groups_by_key(db, root_folder_id)
    await _confirm(db, groups["saga"].id, 101)  # as proposed
    await _confirm(db, groups["sagga"].id, 202)  # user override

    summary = await execute_library_import(
        db,
        settings,
        [groups["saga"].id, groups["sagga"].id],
        commands=commands,
        factory=factory,
    )

    assert "imported=2" in summary
    # Both series exist; in-place mode pinned each to its scanned folder.
    async with db.read_session() as session:
        saga = (
            await session.execute(select(SeriesRow).where(SeriesRow.cv_volume_id == 101))
        ).scalars().one()
        girls = (
            await session.execute(select(SeriesRow).where(SeriesRow.cv_volume_id == 202))
        ).scalars().one()
        assert saga.path == str(root_folder_path / "Saga (2012)")
        assert girls.path == str(root_folder_path / "Sagg Whatever")
        descender_series = (
            await session.execute(select(SeriesRow).where(SeriesRow.cv_volume_id == 303))
        ).scalars().first()
    assert descender_series is None  # deselected group added nothing

    assert len(await _issue_file_paths(db, 101)) == 1
    girls_files = await _issue_file_paths(db, 202)
    assert len(girls_files) == 1
    assert girls_files[0].startswith(str(overridden.parent))  # stayed in its folder

    after = await _groups_by_key(db, root_folder_id)
    assert after["saga"].state == "imported"
    assert after["sagga"].state == "imported"
    assert after["descender"].state == "proposed"  # stays staged, untouched


@pytest.mark.req("FRG-IMP-023")
async def test_in_place_registers_files_without_moving_them(
    db, tmp_path, root_folder_id, root_folder_path
):
    """in_place (default) + rename disabled: the file is registered at its
    existing path — same inode, same mtime, no move/copy/rename."""
    cfg = tmp_path / "cfg-noren"
    cfg.mkdir()
    settings = flows_settings(cfg, rename_enabled=False)
    original = make_large_cbz(root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz")
    stat_before = original.stat()

    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    groups = await _groups_by_key(db, root_folder_id)
    await _confirm(db, groups["saga"].id, 101)

    summary = await execute_library_import(
        db, settings, [groups["saga"].id], commands=commands, factory=factory
    )

    assert "imported=1" in summary
    paths = await _issue_file_paths(db, 101)
    assert paths == [str(original)]  # registered AT the existing path
    stat_after = original.stat()
    assert stat_after.st_ino == stat_before.st_ino  # same inode: never moved
    assert stat_after.st_mtime_ns == stat_before.st_mtime_ns  # never rewritten
    after = await _groups_by_key(db, root_folder_id)
    assert after["saga"].state == "imported"
    assert "imported=1" in (after["saga"].message or "")


@pytest.mark.req("FRG-IMP-023")
async def test_move_mode_routes_through_normal_placement(
    db, tmp_path, root_folder_id, root_folder_path
):
    """library_import_mode=move: the series gets the normal root-relative
    folder and the file moves/renames through place_file like a download."""
    cfg = tmp_path / "cfg-move"
    cfg.mkdir()
    settings = flows_settings(cfg, library_import_mode="move")
    original = make_large_cbz(root_folder_path / "saga-dump" / "Saga 001 (2012).cbz")

    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    groups = await _groups_by_key(db, root_folder_id)
    await _confirm(db, groups["saga"].id, 101)

    summary = await execute_library_import(
        db, settings, [groups["saga"].id], commands=commands, factory=factory
    )

    assert "imported=1" in summary
    async with db.read_session() as session:
        series = (
            await session.execute(select(SeriesRow).where(SeriesRow.cv_volume_id == 101))
        ).scalars().one()
    # Normal build_series_path under the batch root, not the scanned folder.
    assert series.path == str(root_folder_path / "Saga (2012)")
    paths = await _issue_file_paths(db, 101)
    assert len(paths) == 1
    placed = Path(paths[0])
    assert placed.parent == root_folder_path / "Saga (2012)"
    assert placed.exists()
    assert not original.exists()  # moved out of the scanned folder


@pytest.mark.req("FRG-IMP-023")
async def test_blocked_files_leave_group_reviewable_with_visible_reasons(
    db, settings, root_folder_id, root_folder_path
):
    """A group whose file fails the safety specs stays confirmed with the
    blocked reasons visible on the staging row — never silently dropped."""
    corrupt = root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"not a zip at all" * 20_000)  # big enough, invalid

    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    groups = await _groups_by_key(db, root_folder_id)
    await _confirm(db, groups["saga"].id, 101)

    summary = await execute_library_import(
        db, settings, [groups["saga"].id], commands=commands, factory=factory
    )

    assert summary == "blocked=1"
    after = await _groups_by_key(db, root_folder_id)
    group = after["saga"]
    assert group.state == "confirmed"  # re-runnable after the user fixes it
    assert "blocked=1" in (group.message or "")
    assert "Saga 001 (2012).cbz" in (group.message or "")
    assert await _issue_file_paths(db, 101) == []
