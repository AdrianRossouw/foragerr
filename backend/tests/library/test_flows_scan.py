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
async def test_scan_does_not_misattribute_a_longer_named_series_file(
    db, settings, root_folder_id, format_profile_id, tmp_path
):
    """A file for a different, longer-named series (misfiled under a
    shorter series whose name is a prefix of it) must NOT match — the
    subset-title tolerance is one-directional (see _series_title_matches)."""
    series_dir = tmp_path / "Batman (1940)"
    series_dir.mkdir()
    async with db.write_session() as session:
        series = await repo.create_series(
            session, cv_volume_id=4, title="Batman", start_year=1940,
            format_profile_id=format_profile_id, root_folder_id=root_folder_id,
            path=str(series_dir),
        )
        batman_1 = await repo.create_issue(
            session, series_id=series.id, cv_issue_id=1, issue_number="1"
        )
        series_id, batman_1_id = series.id, batman_1.id
    # Misfiled: belongs to the distinct series "Batman Beyond", not "Batman".
    (series_dir / "Batman Beyond 001 (1999).cbz").write_bytes(b"x" * 10)

    summary = await scan_series(db, settings, series_id)
    assert summary == "matched=0 unmatched=1"
    assert await _files_for(db, batman_1_id) == []


@pytest.mark.req("FRG-SER-005")
async def test_scan_uses_offload_when_supplied(
    db, settings, root_folder_id, format_profile_id, tmp_path
):
    """The directory walk runs through offload when supplied (the command
    handler passes ctx.offload so it never blocks the event loop), and
    falls back to an inline call when omitted (existing direct-call tests
    above rely on this default)."""
    series_dir = tmp_path / "Saga (2012)"
    series_dir.mkdir()
    async with db.write_session() as session:
        series = await repo.create_series(
            session, cv_volume_id=5, title="Saga", start_year=2012,
            format_profile_id=format_profile_id, root_folder_id=root_folder_id,
            path=str(series_dir),
        )
        series_id = series.id
    (series_dir / "Saga 001 (2012).cbz").write_bytes(b"x" * 10)

    calls = []

    async def fake_offload(func, *args, **kwargs):
        calls.append((func, args))
        return func(*args, **kwargs)

    summary = await scan_series(db, settings, series_id, offload=fake_offload)
    assert summary == "matched=0 unmatched=1"  # no issues registered
    assert len(calls) == 1


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
