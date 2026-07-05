"""Series edit + delete flows (FRG-SER-014, FRG-SER-008 path edit)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from foragerr.library import paths, repo
from foragerr.library.flows import (
    DeleteFilesNotSupportedError,
    SeriesNotFoundError,
    SeriesValidationError,
    delete_series,
    edit_series,
)
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow


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


@pytest.mark.req("FRG-SER-014")
async def test_delete_with_files_is_501_and_touches_nothing(
    db, root_folder_id, root_folder_path, format_profile_id
):
    series_id = await _make(db, root_folder_id, format_profile_id, root_folder_path / "Saga")
    with pytest.raises(DeleteFilesNotSupportedError):
        await delete_series(db, series_id, delete_files=True)
    async with db.read_session() as session:
        assert await session.scalar(select(func.count()).select_from(SeriesRow)) == 1


@pytest.mark.req("FRG-SER-014")
async def test_edit_and_delete_unknown_series_raise_not_found(db):
    with pytest.raises(SeriesNotFoundError):
        await edit_series(db, 999, monitored=True)
    with pytest.raises(SeriesNotFoundError):
        await delete_series(db, 999)
