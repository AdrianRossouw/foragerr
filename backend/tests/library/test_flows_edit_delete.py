"""Series edit + delete flows (FRG-SER-014, FRG-SER-008 path edit,
FRG-API-003 delete-files)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from foragerr.importer import history
from foragerr.library import paths, repo
from foragerr.library.flows import (
    SeriesNotFoundError,
    SeriesValidationError,
    delete_series,
    edit_series,
)
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow

from http_support import make_settings


async def _make(db, root_folder_id, format_profile_id, path: Path, *, cv=1) -> int:
    async with db.write_session() as session:
        series = await repo.create_series(
            session, cv_volume_id=cv, title="Saga", start_year=2012,
            format_profile_id=format_profile_id, root_folder_id=root_folder_id,
            path=str(path),
        )
        return series.id


@pytest.mark.req("FRG-SER-014")
async def test_edit_updates_supplied_fields(
    db, root_folder_id, root_folder_path, format_profile_id
):
    series_id = await _make(db, root_folder_id, format_profile_id, root_folder_path / "Saga")
    updated = await edit_series(
        db, series_id, monitored=False, monitor_new_items="none"
    )
    assert updated.monitored is False
    async with db.read_session() as session:
        series = await repo.get_series(session, series_id)
    assert series.monitored is False
    assert series.monitor_new_items == "none"


@pytest.mark.req("FRG-SER-014")
async def test_edit_rejects_invalid_monitor_new_items(
    db, root_folder_id, root_folder_path, format_profile_id
):
    series_id = await _make(db, root_folder_id, format_profile_id, root_folder_path / "Saga")
    with pytest.raises(SeriesValidationError):
        await edit_series(db, series_id, monitor_new_items="sometimes")


@pytest.mark.req("FRG-SER-008")
async def test_path_change_renames_directory(
    db, root_folder_id, root_folder_path, format_profile_id
):
    old_dir = root_folder_path / "Saga (2012)"
    old_dir.mkdir(parents=True)
    (old_dir / "marker.txt").write_text("here")
    series_id = await _make(db, root_folder_id, format_profile_id, old_dir)

    new_dir = root_folder_path / "Saga Renamed"
    await edit_series(db, series_id, path=str(new_dir))

    async with db.read_session() as session:
        series = await repo.get_series(session, series_id)
    assert Path(series.path) == new_dir.resolve()
    assert not old_dir.exists()
    assert (new_dir / "marker.txt").read_text() == "here"


@pytest.mark.req("FRG-SER-008")
async def test_path_change_outside_root_rejected(
    db, root_folder_id, root_folder_path, format_profile_id, tmp_path
):
    series_id = await _make(db, root_folder_id, format_profile_id, root_folder_path / "Saga")
    with pytest.raises(SeriesValidationError):
        await edit_series(db, series_id, path=str(tmp_path / "elsewhere" / "Saga"))
    async with db.read_session() as session:
        series = await repo.get_series(session, series_id)
    assert Path(series.path) == (root_folder_path / "Saga")  # unchanged


@pytest.mark.req("FRG-SER-008")
async def test_rename_failure_rolls_back_row(
    db, monkeypatch, root_folder_id, root_folder_path, format_profile_id
):
    old_dir = root_folder_path / "Saga (2012)"
    old_dir.mkdir(parents=True)
    series_id = await _make(db, root_folder_id, format_profile_id, old_dir)

    def _boom(old, new):
        raise OSError("disk full")

    monkeypatch.setattr(paths, "rename_series_directory", _boom)
    with pytest.raises(OSError):
        await edit_series(db, series_id, path=str(root_folder_path / "New Name"))

    async with db.read_session() as session:
        series = await repo.get_series(session, series_id)
    assert Path(series.path) == old_dir  # row rolled back to the original path


@pytest.mark.req("FRG-SER-008")
async def test_root_folder_change_without_path_requires_current_path_under_new_root(
    db, root_folder_id, root_folder_path, format_profile_id, tmp_path
):
    """root_folder_id alone (no path) must not silently desync the row: if
    the series' current path isn't under the new root, reject it."""
    series_id = await _make(db, root_folder_id, format_profile_id, root_folder_path / "Saga")

    other_root = tmp_path / "other-root"
    other_root.mkdir()
    async with db.write_session() as session:
        other = await repo.create_root_folder(session, str(other_root))
        other_root_id = other.id

    with pytest.raises(SeriesValidationError):
        await edit_series(db, series_id, root_folder_id=other_root_id)

    async with db.read_session() as session:
        series = await repo.get_series(session, series_id)
    # unchanged: root_folder_id must not diverge from path's actual root
    assert series.root_folder_id == root_folder_id
    assert Path(series.path) == (root_folder_path / "Saga")


@pytest.mark.req("FRG-SER-008")
async def test_edit_path_rejects_collision_with_another_series(
    db, root_folder_id, root_folder_path, format_profile_id
):
    """A PUT path change that would collide with another series' stored path
    must reject before renaming anything on disk."""
    taken_dir = root_folder_path / "Already Taken"
    taken_dir.mkdir(parents=True)
    await _make(db, root_folder_id, format_profile_id, taken_dir, cv=1)

    old_dir = root_folder_path / "Saga (2012)"
    old_dir.mkdir(parents=True)
    series_id = await _make(db, root_folder_id, format_profile_id, old_dir, cv=2)

    with pytest.raises(SeriesValidationError):
        await edit_series(db, series_id, path=str(taken_dir))

    async with db.read_session() as session:
        series = await repo.get_series(session, series_id)
    assert Path(series.path) == old_dir  # unchanged
    assert old_dir.exists()  # never renamed away


@pytest.mark.req("FRG-SER-014")
async def test_delete_removes_cached_cover_files(
    db, root_folder_id, root_folder_path, format_profile_id
):
    from foragerr.library.flows._common import cover_paths
    from foragerr.config import Settings

    series_id = await _make(db, root_folder_id, format_profile_id, root_folder_path / "Saga")
    settings = Settings(config_dir=root_folder_path.parent / "cfg")
    settings.config_dir.mkdir(exist_ok=True)
    cover_path, url_path = cover_paths(settings, series_id)
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    cover_path.write_bytes(b"jpeg-bytes")
    url_path.write_text("https://example.com/cover.jpg")

    await delete_series(db, series_id, settings=settings)

    assert not cover_path.exists()
    assert not url_path.exists()


@pytest.mark.req("FRG-SER-014")
async def test_delete_keeps_files_and_cascades_rows(
    db, root_folder_id, root_folder_path, format_profile_id, tmp_path
):
    series_dir = root_folder_path / "Saga"
    series_dir.mkdir(parents=True)
    on_disk = series_dir / "Saga 001.cbz"
    on_disk.write_bytes(b"comic")
    series_id = await _make(db, root_folder_id, format_profile_id, series_dir)
    async with db.write_session() as session:
        iss = await repo.create_issue(session, series_id=series_id, cv_issue_id=1, issue_number="1")
        await repo.add_issue_file(session, issue_id=iss.id, path=str(on_disk), size=5)

    await delete_series(db, series_id, delete_files=False)

    async with db.read_session() as session:
        assert await session.scalar(select(func.count()).select_from(SeriesRow)) == 0
        assert await session.scalar(select(func.count()).select_from(IssueRow)) == 0
        assert await session.scalar(select(func.count()).select_from(IssueFileRow)) == 0
    assert on_disk.exists()  # the comic file stays on disk


# --- delete_files=True (FRG-API-003 delete-files scenario, the recycle-bin requirement) -------


async def _make_with_files(
    db, root_folder_id, format_profile_id, series_dir: Path, n_files: int
) -> tuple[int, list[Path]]:
    """A series with ``n_files`` issues, each with one on-disk file."""
    series_dir.mkdir(parents=True, exist_ok=True)
    series_id = await _make(db, root_folder_id, format_profile_id, series_dir)
    files: list[Path] = []
    async with db.write_session() as session:
        for n in range(1, n_files + 1):
            issue = await repo.create_issue(
                session, series_id=series_id, cv_issue_id=n, issue_number=str(n)
            )
            path = series_dir / f"Saga {n:03d}.cbz"
            path.write_bytes(f"saga-{n}-bytes".encode())
            await repo.add_issue_file(
                session, issue_id=issue.id, path=str(path), size=path.stat().st_size
            )
            files.append(path)
    return series_id, files


async def _row_counts(db) -> tuple[int, int, int]:
    async with db.read_session() as session:
        return (
            await session.scalar(select(func.count()).select_from(SeriesRow)),
            await session.scalar(select(func.count()).select_from(IssueRow)),
            await session.scalar(select(func.count()).select_from(IssueFileRow)),
        )


async def _file_deleted_events(db) -> list:
    async with db.read_session() as session:
        events = await history.all_events(session)
    return [e for e in events if e.event_type == history.EVENT_FILE_DELETED]


@pytest.mark.req("FRG-API-003")
async def test_delete_files_routes_every_file_through_the_bin_before_rows(
    db, root_folder_id, root_folder_path, format_profile_id, tmp_path
):
    series_id, files = await _make_with_files(
        db, root_folder_id, format_profile_id, root_folder_path / "Saga", 2
    )
    bin_root = tmp_path / "recycle"
    bin_root.mkdir()
    (tmp_path / "cfg").mkdir(exist_ok=True)
    settings = make_settings(tmp_path / "cfg", recycle_bin_path=str(bin_root))

    await delete_series(db, series_id, delete_files=True, settings=settings)

    assert await _row_counts(db) == (0, 0, 0)  # rows removed (after the moves)
    for path in files:
        assert not path.exists()  # moved, never hard-deleted
    assert len(list(bin_root.rglob("*.cbz"))) == 2  # both preserved in the bin

    # One file_deleted event per file, each a MANUAL user action with the
    # recycle destination recorded.
    deleted = await _file_deleted_events(db)
    assert len(deleted) == 2
    for event in deleted:
        assert event.source == history.SOURCE_MANUAL
        assert event.quarantine_path is not None
        assert str(bin_root) in event.quarantine_path


@pytest.mark.req("FRG-API-003")
async def test_delete_files_without_bin_deletes_permanently_after_commit(
    db, root_folder_id, root_folder_path, format_profile_id, tmp_path
):
    series_id, files = await _make_with_files(
        db, root_folder_id, format_profile_id, root_folder_path / "Saga", 2
    )
    (tmp_path / "cfg").mkdir(exist_ok=True)
    settings = make_settings(tmp_path / "cfg")  # no recycle bin

    await delete_series(db, series_id, delete_files=True, settings=settings)

    assert await _row_counts(db) == (0, 0, 0)
    for path in files:
        assert not path.exists()  # permanently deleted (no bin configured)
    deleted = await _file_deleted_events(db)
    assert len(deleted) == 2
    for event in deleted:
        assert event.source == history.SOURCE_MANUAL
        assert event.quarantine_path is None  # nothing recycled


@pytest.mark.req("FRG-API-003")
async def test_delete_files_mid_failure_leaves_rows_intact_and_compensates(
    db, root_folder_id, root_folder_path, format_profile_id, tmp_path, monkeypatch
):
    """The pinned guarantee: files move to the bin BEFORE any row is removed,
    and any failure compensates the moves already made. A recycle failure on
    file 2 of 3 leaves ALL rows intact and file 1 restored to its original
    path — never rows deleted with files untouched, never files stranded in
    the bin with live rows."""
    from foragerr.importer import fileops

    series_id, files = await _make_with_files(
        db, root_folder_id, format_profile_id, root_folder_path / "Saga", 3
    )
    bin_root = tmp_path / "recycle"
    bin_root.mkdir()
    (tmp_path / "cfg").mkdir(exist_ok=True)
    settings = make_settings(tmp_path / "cfg", recycle_bin_path=str(bin_root))

    real_recycle = fileops.recycle_file
    calls = {"n": 0}

    def failing_recycle(src, recycle_root, *, now=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk error moving file 2")
        return real_recycle(src, recycle_root, now=now)

    monkeypatch.setattr(fileops, "recycle_file", failing_recycle)

    with pytest.raises(OSError):
        await delete_series(db, series_id, delete_files=True, settings=settings)

    assert await _row_counts(db) == (1, 3, 3)  # every row intact
    for path in files:
        assert path.exists()  # file 1's move was compensated; 2 and 3 untouched
    assert list(bin_root.rglob("*.cbz")) == []  # nothing stranded in the bin
    assert await _file_deleted_events(db) == []  # no phantom history


@pytest.mark.req("FRG-API-003")
async def test_delete_files_commit_failure_compensates_all_moves(
    db, root_folder_id, root_folder_path, format_profile_id, tmp_path, monkeypatch
):
    """Same guarantee at the other failure point: every move succeeded but the
    row-removal transaction fails — all files are restored, rows intact."""
    from foragerr.library.flows import edit_delete

    series_id, files = await _make_with_files(
        db, root_folder_id, format_profile_id, root_folder_path / "Saga", 2
    )
    bin_root = tmp_path / "recycle"
    bin_root.mkdir()
    (tmp_path / "cfg").mkdir(exist_ok=True)
    settings = make_settings(tmp_path / "cfg", recycle_bin_path=str(bin_root))

    async def boom(db_, series_id_, files_, recycled_, now_):
        raise RuntimeError("row removal failed mid-commit")

    monkeypatch.setattr(edit_delete, "_commit_series_deletion", boom)

    with pytest.raises(RuntimeError):
        await delete_series(db, series_id, delete_files=True, settings=settings)

    assert await _row_counts(db) == (1, 2, 2)
    for path in files:
        assert path.exists()  # both moves compensated
    assert list(bin_root.rglob("*.cbz")) == []


@pytest.mark.req("FRG-API-003")
async def test_delete_files_summary_reports_binned_count(
    db, root_folder_id, root_folder_path, format_profile_id, tmp_path
):
    """The command surfaces a recycled-paths summary (finding 6): delete_series
    returns an `imported`-style one-liner naming how many files were deleted and
    how many of those were binned (per-file paths already live in the events)."""
    series_id, files = await _make_with_files(
        db, root_folder_id, format_profile_id, root_folder_path / "Saga", 2
    )
    bin_root = tmp_path / "recycle"
    bin_root.mkdir()
    (tmp_path / "cfg").mkdir(exist_ok=True)
    settings = make_settings(tmp_path / "cfg", recycle_bin_path=str(bin_root))

    summary = await delete_series(
        db, series_id, delete_files=True, settings=settings
    )
    assert "files=2" in summary and "binned=2" in summary


@pytest.mark.req("FRG-API-003")
async def test_stranded_bin_file_on_failed_compensation_is_recorded(
    db, root_folder_id, root_folder_path, format_profile_id, tmp_path, monkeypatch
):
    """Finding 5: when the row-removal commit fails AND the compensating restore
    ALSO fails, the file is stranded in the bin. Its location must be recoverable
    from the DB — a durable `file_deleted` event (source=manual) carrying the
    quarantine_path and a compensation-leftover marker — not only a warning log.
    The series rows stay intact (the deletion rolled back)."""
    from foragerr.importer import fileops
    from foragerr.library.flows import edit_delete

    series_id, files = await _make_with_files(
        db, root_folder_id, format_profile_id, root_folder_path / "Saga", 2
    )
    bin_root = tmp_path / "recycle"
    bin_root.mkdir()
    (tmp_path / "cfg").mkdir(exist_ok=True)
    settings = make_settings(tmp_path / "cfg", recycle_bin_path=str(bin_root))

    async def boom(db_, series_id_, files_, recycled_, now_):
        raise RuntimeError("row removal failed mid-commit")

    def failing_restore(*args, **kwargs):
        raise OSError("cannot restore from the bin")

    monkeypatch.setattr(edit_delete, "_commit_series_deletion", boom)
    monkeypatch.setattr(fileops, "place_file", failing_restore)

    with pytest.raises(RuntimeError):
        await delete_series(db, series_id, delete_files=True, settings=settings)

    # Rows intact: the deletion transaction rolled back.
    assert await _row_counts(db) == (1, 2, 2)
    # The files are stranded in the bin (restore failed), not at their origin.
    assert len(list(bin_root.rglob("*.cbz"))) == 2
    for path in files:
        assert not path.exists()

    # Durable, DB-recoverable record of each stranded file's bin location.
    deleted = await _file_deleted_events(db)
    assert len(deleted) == 2
    for event in deleted:
        assert event.source == history.SOURCE_MANUAL
        assert event.quarantine_path is not None
        assert str(bin_root) in event.quarantine_path
        assert history.decode_data(event.data).get("compensation_leftover") is True


@pytest.mark.req("FRG-SER-014")
async def test_edit_and_delete_unknown_series_raise_not_found(db):
    with pytest.raises(SeriesNotFoundError):
        await edit_series(db, 999, monitored=True)
    with pytest.raises(SeriesNotFoundError):
        await delete_series(db, 999)
    # delete_files=True no longer short-circuits with 501-style precedence:
    # an unknown id is a plain not-found on this path too (FRG-API-003).
    with pytest.raises(SeriesNotFoundError):
        await delete_series(db, 999, delete_files=True)
