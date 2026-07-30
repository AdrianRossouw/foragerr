"""The read-only reference library: index in place, never write, never acquire.

FRG-SER-021 (read-only root + fail-closed write boundary), FRG-IMP-028
(index-in-place import), FRG-SER-022 (browse/serve-only series).

The read-only flag is a property of the ROOT ROW, deliberately independent of
the mount's real permissions: these tests point it at a perfectly writable
temp directory precisely so a passing assertion means foragerr chose not to
write, rather than the filesystem having stopped it.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import func, select

from flows_support import FakeCV, build_factory, flows_settings, issue
from foragerr.commands import CommandService
from foragerr.db import utcnow
from foragerr.library import repo
from foragerr.library.flows import (
    add_series,
    convert_issue,
    convert_series,
    delete_issue_file,
    delete_series,
    edit_series,
    execute_library_import,
    rename_series,
    rescan_series,
    scan_library_root,
)
from foragerr.library.flows._common import SeriesValidationError
from foragerr.library.flows.library_import import encode_group_files
from foragerr.library.models import (
    IssueFileRow,
    IssueRow,
    LibraryImportGroupRow,
    SeriesRow,
)
from foragerr.library.read_only import (
    ReadOnlySeriesError,
    path_is_read_only,
)
from foragerr.library.read_only import series_is_read_only as read_only_series

_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f9f0000000049454e44ae42"
    "6082"
)


def make_large_cbz(path: Path, *, filler: int = 200 * 1024) -> Path:
    """A valid cbz (>=1 image entry) clearing the junk-size floor."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("page000.png", _PNG_1x1)
        zf.writestr("filler.bin", os.urandom(filler))
    return path


def snapshot(root: Path) -> dict[str, tuple[bool, int, int, int]]:
    """Every entry under ``root`` -> (is_file, inode, size, mtime_ns).

    The zero-write assertion: comparing this before and after an operation
    catches a moved or renamed file (the relative path key), a re-written one
    (inode/mtime), a truncated one (size), a deleted one (a missing key), and
    anything newly created under the root (an extra key) — including a
    directory rename.
    """
    entries: dict[str, tuple[bool, int, int, int]] = {}
    for path in sorted(root.rglob("*")):
        stat = path.stat()
        entries[str(path.relative_to(root))] = (
            path.is_file(),
            stat.st_ino,
            stat.st_size if path.is_file() else 0,
            stat.st_mtime_ns,
        )
    return entries


@pytest.fixture
def read_only_root_path(tmp_path: Path) -> Path:
    path = tmp_path / "reference-library"
    path.mkdir(exist_ok=True)
    return path


@pytest.fixture
async def commands(db, settings, command_registry):
    return CommandService(db, settings)


@pytest.fixture
async def read_only_root_id(db, read_only_root_path: Path) -> int:
    async with db.write_session() as session:
        row = await repo.create_root_folder(
            session, str(read_only_root_path), read_only=True
        )
        return row.id


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    # Deliberately hostile settings: every media-management seam that can mutate
    # a file is switched ON. Move mode + renaming relocate and rename;
    # ComicInfo tagging and CBR→CBZ conversion REWRITE the file after it is
    # placed (so they bypass the placement boundary entirely and must be
    # forced off in their own right); a recycle bin makes replacement disposal
    # a move. Every one of them would mutate the root if the read-only
    # boundary did not override it.
    return flows_settings(
        cfg,
        library_import_mode="move",
        rename_enabled=True,
        comicinfo_tag_on_import=True,
        convert_cbr_to_cbz=True,
        recycle_bin_path=str(tmp_path / "bin"),
    )


@pytest.fixture
def no_bin_settings(tmp_path: Path):
    """The hostile settings with the DEFAULT (empty) recycle-bin path.

    ``recycle_bin_path`` defaults to ``""``, which makes replacement disposal a
    permanent ``os.remove`` rather than a reversible move — so this is the
    configuration in which a disposal bug destroys the operator's file outright,
    and the one the duplicate/upgrade tests below must use."""
    cfg = tmp_path / "cfg-no-bin"
    cfg.mkdir()
    return flows_settings(
        cfg,
        library_import_mode="move",
        rename_enabled=True,
        comicinfo_tag_on_import=True,
        convert_cbr_to_cbz=True,
    )


async def _seed_series(
    db, *, root_folder_id: int, series_path: Path, file_path: Path | None = None
) -> tuple[int, int, int | None]:
    """A series + one issue on ``root_folder_id``, optionally with one indexed
    file. Bypasses the add flow (no ComicVine call). Returns
    ``(series_id, issue_id, issue_file_id)``."""
    from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

    async with db.write_session() as session:
        profile_id = await session.scalar(
            select(FormatProfileRow.id).where(
                FormatProfileRow.name == DEFAULT_PROFILE_NAME
            )
        )
        series = await repo.create_series(
            session,
            cv_volume_id=4242,
            title="Example Series",
            start_year=2012,
            format_profile_id=profile_id,
            root_folder_id=root_folder_id,
            path=str(series_path),
        )
        issue_row = await repo.create_issue(
            session,
            series_id=series.id,
            cv_issue_id=91001,
            issue_number="1",
        )
        file_id = None
        if file_path is not None:
            file_row = await repo.add_issue_file(
                session,
                issue_id=issue_row.id,
                path=str(file_path),
                size=file_path.stat().st_size,
            )
            file_id = file_row.id
        return series.id, issue_row.id, file_id


async def _stage_group(
    db,
    *,
    root_folder_id: int,
    folder: Path,
    files: list[Path],
    cv_volume_id: int,
) -> int:
    """A CONFIRMED staging group over ``files``, built directly.

    Bypasses the scan so the group's exact file list is the test's choice — the
    disposal cases below need a specific pair of files in a specific folder,
    which a scan's own grouping would not guarantee."""
    async with db.write_session() as session:
        group = LibraryImportGroupRow(
            matching_key="example series",
            root_folder_id=root_folder_id,
            folder=str(folder),
            files=encode_group_files([(str(p), p.stat().st_size) for p in files]),
            confidence=1.0,
            state="confirmed",
            confirmed_cv_volume_id=cv_volume_id,
            scanned_at=utcnow(),
        )
        session.add(group)
        await session.flush()
        return group.id


# --- FRG-IMP-028: index in place, mutate nothing -----------------------------


@pytest.mark.req("FRG-IMP-028")
@pytest.mark.req("FRG-SER-021")
@pytest.mark.req("FRG-SER-022")
async def test_read_only_import_indexes_in_place_and_writes_nothing(
    db, settings, read_only_root_id, read_only_root_path
):
    """A confirmed group under a read-only root registers its series and files
    at their EXISTING paths — no move, no rename, no copy — even though the
    settings ask for move mode with renaming on. The resulting series is
    browse-only: unmonitored, with no acquisition intent recorded."""
    # A folder named the way the OPERATOR named it, not the way foragerr's
    # template would: move mode would relocate the file into a canonical
    # "Example Series (2012)" folder, so the snapshot below catches the move.
    original = make_large_cbz(
        read_only_root_path / "example series v1" / "Example Series 001 (2012).cbz"
    )
    before = snapshot(read_only_root_path)

    cv = (
        FakeCV()
        .volume(101, name="Example Series", start_year=2012)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)

    await scan_library_root(db, settings, read_only_root_id, factory=factory)
    async with db.read_session() as session:
        group_id = await session.scalar(
            select(LibraryImportGroupRow.id).where(
                LibraryImportGroupRow.root_folder_id == read_only_root_id
            )
        )
    async with db.write_session() as session:
        group = await session.get(LibraryImportGroupRow, group_id)
        group.state = "confirmed"
        group.confirmed_cv_volume_id = 101

    summary = await execute_library_import(
        db, settings, [group_id], commands=commands, factory=factory
    )

    assert "imported=1" in summary
    assert snapshot(read_only_root_path) == before  # not one byte moved
    async with db.read_session() as session:
        series = (
            await session.execute(select(SeriesRow).where(SeriesRow.cv_volume_id == 101))
        ).scalars().one()
        paths = (
            (
                await session.execute(
                    select(IssueFileRow.path)
                    .join(IssueRow, IssueFileRow.issue_id == IssueRow.id)
                    .where(IssueRow.series_id == series.id)
                )
            )
            .scalars()
            .all()
        )
    assert list(paths) == [str(original)]  # registered AT the existing path
    assert series.path == str(original.parent)  # the folder as it already is
    assert series.monitored is False  # browse-only (FRG-SER-022)
    assert series.monitor_new_items == "none"


@pytest.mark.req("FRG-IMP-028")
@pytest.mark.req("FRG-SER-021")
async def test_a_second_copy_of_an_indexed_issue_never_disposes_the_original(
    db, no_bin_settings, read_only_root_id, read_only_root_path
):
    """A reference folder holding TWO copies of one issue must lose neither.

    This is the whole feature's primary flow, not an edge case: a real
    collection routinely carries a second scan (or a format twin) of the same
    issue. The first copy indexes; the second maps to the same issue, so the
    pipeline sees ``existing_present`` and — as an upgrade or a same-rung
    duplicate win — DISPOSES of the loser. With the default empty recycle-bin
    path that disposal is a permanent ``os.remove`` of the operator's file, and
    it happens on the in-place branch where nothing is ever placed. The
    boundary therefore has to refuse any candidate that displaces an indexed
    file, not just any candidate that would be moved.
    """
    settings = no_bin_settings
    group_folder = read_only_root_path / "example series v1"
    indexed = make_large_cbz(
        group_folder / "Example Series 001 (2012).cbz", filler=200 * 1024
    )
    # Larger, so it WINS the duplicate/upgrade contest and the already-indexed
    # copy becomes the loser to be disposed of.
    second_copy = make_large_cbz(
        group_folder / "Example Series 001 (2012) rescan.cbz", filler=400 * 1024
    )
    series_id, _issue_id, _file_id = await _seed_series(
        db, root_folder_id=read_only_root_id, series_path=group_folder,
        file_path=indexed,
    )
    group_id = await _stage_group(
        db,
        root_folder_id=read_only_root_id,
        folder=group_folder,
        files=[indexed, second_copy],
        cv_volume_id=4242,
    )
    before = snapshot(read_only_root_path)

    cv = (
        FakeCV()
        .volume(4242, name="Example Series", start_year=2012)
        .issues(4242, [issue(91001, "1", cover_date="2012-03-01")])
    )
    factory = build_factory(settings, cv.handler())
    summary = await execute_library_import(
        db, settings, [group_id], commands=CommandService(db, settings),
        factory=factory,
    )

    assert summary == "blocked=1"
    assert snapshot(read_only_root_path) == before  # BOTH copies still there
    async with db.read_session() as session:
        paths = (
            (
                await session.execute(
                    select(IssueFileRow.path)
                    .join(IssueRow, IssueFileRow.issue_id == IssueRow.id)
                    .where(IssueRow.series_id == series_id)
                )
            )
            .scalars()
            .all()
        )
        group = await session.get(LibraryImportGroupRow, group_id)
        message = group.message or ""
    # The original keeps its row; the refusal is visible, not silent.
    assert list(paths) == [str(indexed)]
    assert "read-only reference library" in message


@pytest.mark.req("FRG-SER-021")
async def test_read_only_rescan_is_skipped_and_writes_nothing(
    db, settings, read_only_root_id, read_only_root_path
):
    """Rescan is the per-series file MANAGER — it would move untracked files
    into place — so it skips a read-only series cleanly rather than erroring,
    and an untracked file dropped in the folder is left exactly where it is."""
    series_path = read_only_root_path / "Example Series (2012)"
    indexed = make_large_cbz(series_path / "Example Series 001 (2012).cbz")
    series_id, _issue_id, _file_id = await _seed_series(
        db, root_folder_id=read_only_root_id, series_path=series_path,
        file_path=indexed,
    )
    # A stray file rescan would normally claim, rename, and index.
    make_large_cbz(series_path / "Example Series 002 (2012).cbz")
    before = snapshot(read_only_root_path)

    report = await rescan_series(db, settings, series_id)

    assert report.imported == () and report.blocked == ()
    assert snapshot(read_only_root_path) == before
    async with db.read_session() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(IssueFileRow)
            .join(IssueRow, IssueFileRow.issue_id == IssueRow.id)
            .where(IssueRow.series_id == series_id)
        )
    assert count == 1  # the stray file was never indexed either


# --- FRG-SER-021: every write path refuses, fail-closed ----------------------


@pytest.mark.req("FRG-SER-021")
async def test_read_only_series_refuses_delete_files_and_deletes_nothing(
    db, settings, read_only_root_id, read_only_root_path
):
    series_path = read_only_root_path / "Example Series (2012)"
    indexed = make_large_cbz(series_path / "Example Series 001 (2012).cbz")
    series_id, _issue_id, _file_id = await _seed_series(
        db, root_folder_id=read_only_root_id, series_path=series_path,
        file_path=indexed,
    )
    before = snapshot(read_only_root_path)

    with pytest.raises(ReadOnlySeriesError) as excinfo:
        await delete_series(db, series_id, delete_files=True, settings=settings)

    assert "read-only reference library" in str(excinfo.value)
    assert snapshot(read_only_root_path) == before
    async with db.read_session() as session:
        # The refusal is fail-closed: the rows survive too, so nothing is left
        # half-deleted for the operator to reconstruct.
        assert await repo.get_series(session, series_id) is not None


@pytest.mark.req("FRG-SER-021")
async def test_read_only_series_refuses_single_file_delete(
    db, settings, read_only_root_id, read_only_root_path
):
    series_path = read_only_root_path / "Example Series (2012)"
    indexed = make_large_cbz(series_path / "Example Series 001 (2012).cbz")
    _series_id, _issue_id, file_id = await _seed_series(
        db, root_folder_id=read_only_root_id, series_path=series_path,
        file_path=indexed,
    )
    before = snapshot(read_only_root_path)

    with pytest.raises(ReadOnlySeriesError):
        await delete_issue_file(db, settings, file_id)

    assert snapshot(read_only_root_path) == before
    async with db.read_session() as session:
        assert await session.get(IssueFileRow, file_id) is not None


@pytest.mark.req("FRG-SER-021")
async def test_read_only_series_refuses_rename_and_moves_nothing(
    db, settings, read_only_root_id, read_only_root_path
):
    """A badly named file under a read-only root is exactly what renaming would
    "fix" — and exactly what must not be touched."""
    series_path = read_only_root_path / "Example Series (2012)"
    indexed = make_large_cbz(series_path / "whatever the operator called it.cbz")
    series_id, _issue_id, _file_id = await _seed_series(
        db, root_folder_id=read_only_root_id, series_path=series_path,
        file_path=indexed,
    )
    before = snapshot(read_only_root_path)

    with pytest.raises(ReadOnlySeriesError):
        await rename_series(db, settings, series_id)

    assert snapshot(read_only_root_path) == before


@pytest.mark.req("FRG-SER-021")
async def test_read_only_series_refuses_path_edit_and_renames_no_directory(
    db, settings, read_only_root_id, read_only_root_path
):
    series_path = read_only_root_path / "Example Series (2012)"
    make_large_cbz(series_path / "Example Series 001 (2012).cbz")
    series_id, _issue_id, _file_id = await _seed_series(
        db, root_folder_id=read_only_root_id, series_path=series_path
    )
    before = snapshot(read_only_root_path)

    with pytest.raises(ReadOnlySeriesError):
        await edit_series(
            db, series_id, path=str(read_only_root_path / "Renamed Folder")
        )

    assert snapshot(read_only_root_path) == before
    async with db.read_session() as session:
        row = await repo.get_series(session, series_id)
        assert row.path == str(series_path)


@pytest.mark.req("FRG-SER-021")
async def test_a_series_cannot_be_moved_onto_a_read_only_root(
    db, settings, root_folder_id, root_folder_path, read_only_root_id
):
    """The boundary closes in both directions: a managed series must not be
    relocated onto a root nothing can ever be written to."""
    root_folder_path.mkdir(exist_ok=True)
    series_path = root_folder_path / "Example Series (2012)"
    series_path.mkdir(parents=True)
    series_id, _issue_id, _file_id = await _seed_series(
        db, root_folder_id=root_folder_id, series_path=series_path
    )

    with pytest.raises(ReadOnlySeriesError) as excinfo:
        await edit_series(db, series_id, root_folder_id=read_only_root_id)

    assert "cannot be moved onto it" in str(excinfo.value)
    async with db.read_session() as session:
        row = await repo.get_series(session, series_id)
        assert row.root_folder_id == root_folder_id


@pytest.mark.req("FRG-SER-021")
@pytest.mark.req("FRG-PP-018")
async def test_read_only_series_refuses_on_demand_conversion(
    db, settings, read_only_root_id, read_only_root_path
):
    """On-demand CBR→CBZ conversion writes a new archive beside the source and
    then DELETES the source, and it never routes through the import pipeline —
    so the placement boundary never sees it. Both the per-series and per-issue
    flows refuse, which also closes the command-enqueue route: the flow IS what
    the ``convert-series`` / ``convert-issue`` handlers call."""
    series_path = read_only_root_path / "Example Series (2012)"
    indexed = make_large_cbz(series_path / "Example Series 001 (2012).cbz")
    series_id, issue_id, _file_id = await _seed_series(
        db, root_folder_id=read_only_root_id, series_path=series_path,
        file_path=indexed,
    )
    before = snapshot(read_only_root_path)

    with pytest.raises(ReadOnlySeriesError):
        await convert_series(db, settings, series_id)
    with pytest.raises(ReadOnlySeriesError):
        await convert_issue(db, settings, issue_id)

    assert snapshot(read_only_root_path) == before


@pytest.mark.req("FRG-SER-021")
async def test_a_series_cannot_be_added_with_a_read_only_path_under_a_writable_root(
    db, settings, commands, read_only_root_id, read_only_root_path, root_folder_id,
    root_folder_path,
):
    """The path and the root key must agree. A path override was validated
    against ANY registered root, so an add naming a WRITABLE root while
    pointing INSIDE the reference library produced a series whose files live on
    the read-only mount and whose ``root_folder_id`` says otherwise — every
    guard that reads the key then answers "writable" for the operator's
    originals. The override is confined to the ASSIGNED root instead."""
    root_folder_path.mkdir(exist_ok=True)
    inside_reference = read_only_root_path / "Example Series (2012)"
    inside_reference.mkdir(parents=True)
    factory = build_factory(
        settings, FakeCV().volume(777, name="Example Series").handler()
    )

    with pytest.raises(SeriesValidationError) as excinfo:
        await add_series(
            db,
            settings,
            cv_volume_id=777,
            root_folder_id=root_folder_id,
            commands=commands,
            path_override=str(inside_reference),
            factory=factory,
        )

    assert "does not resolve under root folder" in str(excinfo.value)
    async with db.read_session() as session:
        assert (
            await session.scalar(select(SeriesRow.id).where(SeriesRow.cv_volume_id == 777))
        ) is None


@pytest.mark.req("FRG-SER-021")
async def test_a_writable_series_cannot_be_path_edited_into_a_read_only_root(
    db, settings, read_only_root_id, read_only_root_path, root_folder_id,
    root_folder_path,
):
    """The other direction of the same asymmetry: a path edit was validated
    against ANY root, so a managed series could be given a path inside the
    reference library — and the directory MOVE that follows would drop it
    there. The refusal comes from confining the new path to the series' own
    root, so no directory is renamed."""
    root_folder_path.mkdir(exist_ok=True)
    series_path = root_folder_path / "Example Series (2012)"
    series_path.mkdir(parents=True)
    (series_path / "marker.txt").write_text("here", encoding="utf-8")
    series_id, _issue_id, _file_id = await _seed_series(
        db, root_folder_id=root_folder_id, series_path=series_path
    )
    before = snapshot(read_only_root_path)

    with pytest.raises(SeriesValidationError):
        await edit_series(
            db, series_id, path=str(read_only_root_path / "Stolen Series")
        )

    assert snapshot(read_only_root_path) == before
    assert (series_path / "marker.txt").exists()
    async with db.read_session() as session:
        row = await repo.get_series(session, series_id)
        assert row.path == str(series_path)


@pytest.mark.req("FRG-SER-021")
async def test_rescan_path_override_cannot_walk_a_read_only_root(
    db, settings, read_only_root_id, read_only_root_path, root_folder_id,
    root_folder_path,
):
    """``rescan-series`` takes an unconfined walk override, and the read-only
    check reads the SERIES' root — so a MANAGED series could be rescanned with
    the reference library as its walk path, move-placing every matching
    untracked file out of it. Refused on the override's own location."""
    root_folder_path.mkdir(exist_ok=True)
    series_path = root_folder_path / "Managed Series (2012)"
    series_path.mkdir(parents=True)
    series_id, _issue_id, _file_id = await _seed_series(
        db, root_folder_id=root_folder_id, series_path=series_path
    )
    make_large_cbz(
        read_only_root_path / "example series v1" / "Example Series 001 (2012).cbz"
    )
    before = snapshot(read_only_root_path)

    with pytest.raises(ReadOnlySeriesError):
        await rescan_series(
            db, settings, series_id, path_override=str(read_only_root_path)
        )

    assert snapshot(read_only_root_path) == before
    assert list(series_path.iterdir()) == []


# --- FRG-SER-021: the predicates' own direction -------------------------------


@pytest.mark.req("FRG-SER-021")
async def test_the_root_predicate_fails_closed_on_an_unresolvable_root(
    db, read_only_root_id
):
    """A write boundary must not be opened by a row that cannot be found, so an
    unknown root id reads as READ-ONLY. The series-level predicate keeps the
    opposite direction on purpose: a missing SERIES has no files to protect and
    is the caller's own not-found, so reporting it read-only would turn every
    404 into a 409."""
    async with db.read_session() as session:
        assert await repo.root_is_read_only(session, read_only_root_id) is True
        assert await repo.root_is_read_only(session, 999_999) is True
        assert await repo.series_is_read_only(session, 999_999) is False
        assert await read_only_series(session, 999_999) is False


@pytest.mark.req("FRG-SER-021")
async def test_the_boundary_reads_a_path_inside_a_reference_library(
    db, read_only_root_id, read_only_root_path, root_folder_id, root_folder_path
):
    """The containment half, asserted on its own: a path answers for WHERE it
    is, so the boundary holds for a series row whose stored path and root key
    disagree — and for a location no row describes at all."""
    root_folder_path.mkdir(exist_ok=True)
    inside = read_only_root_path / "example series v1" / "Example Series 001.cbz"
    series_id, _issue_id, _file_id = await _seed_series(
        db, root_folder_id=root_folder_id, series_path=inside.parent
    )

    async with db.read_session() as session:
        assert await path_is_read_only(session, inside) is True
        assert await path_is_read_only(session, root_folder_path / "x.cbz") is False
        # The root KEY says writable; the path says otherwise, and the boundary
        # answers read-only on the strength of the path alone.
        assert await repo.series_is_read_only(session, series_id) is False
        assert await read_only_series(session, series_id) is True


# --- FRG-SER-022: browse/serve-only ------------------------------------------


@pytest.mark.req("FRG-SER-022")
async def test_read_only_series_refuses_monitoring_edits(
    db, settings, read_only_root_id, read_only_root_path
):
    series_path = read_only_root_path / "Example Series (2012)"
    series_path.mkdir(parents=True)
    series_id, _issue_id, _file_id = await _seed_series(
        db, root_folder_id=read_only_root_id, series_path=series_path
    )

    for kwargs in ({"monitored": True}, {"monitor_new_items": "all"}):
        with pytest.raises(ReadOnlySeriesError):
            await edit_series(db, series_id, **kwargs)

    async with db.read_session() as session:
        row = await repo.get_series(session, series_id)
        assert row.monitored is True  # seeded default, left exactly as it was
        assert row.monitor_new_items == "all"


@pytest.mark.req("FRG-SER-022")
async def test_read_only_series_accepts_an_edit_that_restates_browse_only(
    db, settings, read_only_root_id, read_only_root_path
):
    """The refusal is about the STATE asked for, not the field's presence: a
    whole-resource edit echoing a browse-only series' own unmonitored state and
    folder back asks for nothing and must not 409. Refusing on presence would
    make a browse-only series impossible to edit at all through the
    read-modify-write shape a form submits — including the display metadata
    that IS meant to stay editable."""
    series_path = read_only_root_path / "Example Series (2012)"
    series_path.mkdir(parents=True)
    series_id, _issue_id, _file_id = await _seed_series(
        db, root_folder_id=read_only_root_id, series_path=series_path
    )
    async with db.write_session() as session:
        row = await repo.get_series(session, series_id)
        row.monitored = False
        row.monitor_new_items = "none"
    before = snapshot(read_only_root_path)

    edited = await edit_series(
        db,
        series_id,
        monitored=False,
        monitor_new_items="none",
        path=str(series_path),
        root_folder_id=read_only_root_id,
        aliases=["Alternate Name"],
    )

    assert edited.monitored is False
    assert snapshot(read_only_root_path) == before


@pytest.mark.req("FRG-SER-022")
async def test_read_only_series_still_accepts_display_metadata_edits(
    db, settings, read_only_root_id, read_only_root_path
):
    """Browse-only restricts writing and acquiring, not cataloguing: aliases
    and book-type are database columns, so they stay editable — the operator
    can still curate how a reference library READS."""
    from foragerr.library.flows import BooktypeEdit

    series_path = read_only_root_path / "Example Series (2012)"
    series_path.mkdir(parents=True)
    series_id, _issue_id, _file_id = await _seed_series(
        db, root_folder_id=read_only_root_id, series_path=series_path
    )

    row = await edit_series(
        db,
        series_id,
        aliases=["Alternate Name"],
        booktype_op=BooktypeEdit(action="set", booktype="tpb"),
    )

    assert row.booktype == "tpb"


@pytest.mark.req("FRG-SER-022")
async def test_read_only_issues_are_excluded_from_both_acquisition_selectables(
    db, settings, read_only_root_id, read_only_root_path, root_folder_id,
    root_folder_path,
):
    """The two acquisition selectables — wanted (monitored) and missing (the
    monitor-agnostic Search All walk) — both skip a read-only series, so a
    browse-only issue is never a search or backlog target however it is
    reached."""
    root_folder_path.mkdir(exist_ok=True)
    (root_folder_path / "Managed Series").mkdir(parents=True)
    ro_path = read_only_root_path / "Example Series (2012)"
    ro_path.mkdir(parents=True)

    ro_series_id, ro_issue_id, _f = await _seed_series(
        db, root_folder_id=read_only_root_id, series_path=ro_path
    )
    async with db.write_session() as session:
        from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

        profile_id = await session.scalar(
            select(FormatProfileRow.id).where(
                FormatProfileRow.name == DEFAULT_PROFILE_NAME
            )
        )
        managed = await repo.create_series(
            session,
            cv_volume_id=5150,
            title="Managed Series",
            format_profile_id=profile_id,
            root_folder_id=root_folder_id,
            path=str(root_folder_path / "Managed Series"),
        )
        managed_issue = await repo.create_issue(
            session, series_id=managed.id, cv_issue_id=91002, issue_number="1"
        )
        managed_issue_id = managed_issue.id

    async with db.read_session() as session:
        wanted = [
            row.id for row in (await session.execute(repo.wanted_issues())).scalars()
        ]
        missing = [
            row.id for row in (await session.execute(repo.missing_issues())).scalars()
        ]
        # The projection exclusion is defence in depth behind the unmonitored
        # add, so the read-only issue is monitored here on purpose: it must be
        # excluded on the strength of its ROOT alone.
        assert await repo.series_is_read_only(session, ro_series_id) is True

    assert wanted == [managed_issue_id]
    assert missing == [managed_issue_id]
    assert ro_issue_id not in wanted and ro_issue_id not in missing
