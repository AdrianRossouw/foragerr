"""Scan matches on-disk files to issues via the change-2 parser (FRG-SER-005)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.library import repo
from foragerr.library.flows import scan_series
from foragerr.library.models import IssueFileRow

from flows_support import flows_settings


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return flows_settings(cfg)


async def _files_for(db, issue_id: int) -> list[IssueFileRow]:
    async with db.read_session() as session:
        result = await session.execute(
            select(IssueFileRow).where(IssueFileRow.issue_id == issue_id)
        )
        return list(result.scalars().all())


@pytest.mark.req("FRG-SER-005")
async def test_scan_matches_real_shaped_filenames(
    db, settings, root_folder_id, format_profile_id, tmp_path
):
    series_dir = tmp_path / "Paper Girls (2015)"
    series_dir.mkdir()
    async with db.write_session() as session:
        series = await repo.create_series(
            session, cv_volume_id=1, title="Paper Girls", start_year=2015,
            format_profile_id=format_profile_id, root_folder_id=root_folder_id,
            path=str(series_dir),
        )
        i847 = await repo.create_issue(session, series_id=series.id, cv_issue_id=1, issue_number="847")
        await repo.create_issue(session, series_id=series.id, cv_issue_id=2, issue_number="846")
        series_id, i847_id = series.id, i847.id

    # a matching file (real-world shape), a foreign series file, and a non-archive
    (series_dir / "Paper.Girls.847.2015.digital.TheGroup.cbz").write_bytes(b"x" * 100)
    (series_dir / "Totally Different 999 (2015).cbz").write_bytes(b"y" * 50)
    (series_dir / "notes.txt").write_text("ignore me")

    summary = await scan_series(db, settings, series_id)
    assert summary == "matched=1 unmatched=1"

    files = await _files_for(db, i847_id)
    assert len(files) == 1
    assert files[0].path.endswith("Paper.Girls.847.2015.digital.TheGroup.cbz")
    assert files[0].size == 100


@pytest.mark.req("FRG-SER-005")
async def test_scan_is_idempotent(
    db, settings, root_folder_id, format_profile_id, tmp_path
):
    series_dir = tmp_path / "Lazarus (2013)"
    series_dir.mkdir()
    async with db.write_session() as session:
        series = await repo.create_series(
            session, cv_volume_id=2, title="Lazarus", start_year=2013,
            format_profile_id=format_profile_id, root_folder_id=root_folder_id,
            path=str(series_dir),
        )
        await repo.create_issue(session, series_id=series.id, cv_issue_id=9, issue_number="375")
        series_id = series.id
    (series_dir / "Lazarus 375 (2013).cb7").write_bytes(b"z" * 10)

    assert await scan_series(db, settings, series_id) == "matched=1 unmatched=0"
    # second scan does not re-record the same physical file
    assert await scan_series(db, settings, series_id) == "matched=0 unmatched=0"


@pytest.mark.req("FRG-SER-005")
async def test_scan_missing_folder_is_not_an_error(
    db, settings, root_folder_id, format_profile_id, tmp_path
):
    async with db.write_session() as session:
        series = await repo.create_series(
            session, cv_volume_id=3, title="Bone", start_year=1991,
            format_profile_id=format_profile_id, root_folder_id=root_folder_id,
            path=str(tmp_path / "does-not-exist"),
        )
        series_id = series.id
    assert await scan_series(db, settings, series_id) == "matched=0 unmatched=0"
