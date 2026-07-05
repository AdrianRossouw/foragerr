"""RescanSeriesCommand: bounded walk, vanished cleanup, pipeline routing.

FRG-SER-010 — the SER-owned trigger around the shared change-6 import pipeline:
untracked files route through the ONE pipeline, vanished files are cleared (→
derived Wanted), already-linked files are skipped, and unmatched/blocked files
land in a per-series report rather than being silently ignored. Per-series stats
are derived, so a new issue_files row shows up immediately.
"""

from __future__ import annotations

import datetime as dt
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from foragerr.library import repo
from foragerr.library.flows import rescan_series
from foragerr.library.models import IssueFileRow, IssueRow

_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f9f0000000049454e44ae42"
    "6082"
)


def make_large_cbz(path: Path, *, filler: int = 200 * 1024) -> int:
    """A valid cbz (≥1 image entry) large enough to clear the 100 KiB junk floor."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("page000.png", _PNG_1x1)
        zf.writestr("filler.bin", os.urandom(filler))
    return path.stat().st_size


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return SimpleNamespace(config_dir=str(cfg))


async def _mk_series(
    db, tmp_path, root_folder_id, format_profile_id, *, issue="1"
):
    series_dir = tmp_path / "Spawn (2024)"
    series_dir.mkdir(parents=True, exist_ok=True)
    async with db.write_session() as session:
        s = await repo.create_series(
            session,
            cv_volume_id=1,
            title="Spawn",
            start_year=2024,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=str(series_dir),
            monitored=True,
        )
        i = await repo.create_issue(
            session,
            series_id=s.id,
            cv_issue_id=1,
            issue_number=issue,
            cover_date=dt.date(2024, 1, 1),
            monitored=True,
        )
        return s.id, i.id, series_dir


async def _issue_files(db, series_id: int) -> list[IssueFileRow]:
    async with db.read_session() as session:
        rows = (
            await session.execute(
                select(IssueFileRow)
                .join(IssueRow, IssueFileRow.issue_id == IssueRow.id)
                .where(IssueRow.series_id == series_id)
            )
        ).scalars().all()
        for r in rows:
            session.expunge(r)
        return list(rows)


@pytest.mark.req("FRG-SER-010")
async def test_rescan_routes_dropin_through_pipeline_and_stats_update(
    db, settings, root_folder_id, format_profile_id, tmp_path
):
    sid, iid, sdir = await _mk_series(db, tmp_path, root_folder_id, format_profile_id)
    make_large_cbz(sdir / "Spawn 001 (2024).cbz")

    report = await rescan_series(db, settings, sid)

    assert len(report.imported) == 1
    assert report.blocked == ()
    assert report.file_count == 1 and report.issue_count == 1  # derived, immediate
    files = await _issue_files(db, sid)
    assert len(files) == 1 and files[0].issue_id == iid
    assert os.path.exists(files[0].path)


@pytest.mark.req("FRG-SER-010")
async def test_rescan_clears_vanished_file_and_restores_wanted(
    db, settings, root_folder_id, format_profile_id, tmp_path
):
    sid, iid, sdir = await _mk_series(db, tmp_path, root_folder_id, format_profile_id)
    async with db.write_session() as session:
        await repo.add_issue_file(
            session, issue_id=iid, path=str(sdir / "gone.cbz"), size=9_000_000
        )
    # Not wanted while the (phantom) file exists as a row.
    async with db.read_session() as session:
        assert iid not in await repo.wanted_issue_ids(session)

    report = await rescan_series(db, settings, sid)

    assert report.vanished_removed == 1
    assert await _issue_files(db, sid) == []
    async with db.read_session() as session:
        assert iid in await repo.wanted_issue_ids(session)  # returned to Wanted


@pytest.mark.req("FRG-SER-010")
async def test_rescan_records_unmatched_in_report_and_leaves_file(
    db, settings, root_folder_id, format_profile_id, tmp_path
):
    # Series has issue #1; drop a #5 that matches no stored issue → blocked.
    sid, iid, sdir = await _mk_series(db, tmp_path, root_folder_id, format_profile_id)
    orphan = sdir / "Spawn 005 (2024).cbz"
    make_large_cbz(orphan)

    report = await rescan_series(db, settings, sid)

    assert report.imported == ()
    assert len(report.blocked) == 1
    name, reasons = report.blocked[0]
    assert name == "Spawn 005 (2024).cbz"
    assert any("series and issue" in r for r in reasons)
    assert os.path.exists(orphan)  # left in place for the operator
    assert await _issue_files(db, sid) == []


@pytest.mark.req("FRG-SER-010")
async def test_rescan_skips_already_linked_files(
    db, settings, root_folder_id, format_profile_id, tmp_path
):
    sid, iid, sdir = await _mk_series(db, tmp_path, root_folder_id, format_profile_id)
    existing = sdir / "Spawn 001 (2024).cbz"
    make_large_cbz(existing)
    async with db.write_session() as session:
        await repo.add_issue_file(
            session, issue_id=iid, path=str(existing), size=existing.stat().st_size
        )

    report = await rescan_series(db, settings, sid)

    assert report.imported == ()
    assert report.blocked == ()
    assert report.vanished_removed == 0
    assert report.file_count == 1  # the pre-existing link, untouched


@pytest.mark.req("FRG-SER-010")
async def test_rescan_honours_path_override(
    db, settings, root_folder_id, format_profile_id, tmp_path
):
    sid, iid, sdir = await _mk_series(db, tmp_path, root_folder_id, format_profile_id)
    alt = tmp_path / "alt-scan-root"
    make_large_cbz(alt / "Spawn 001 (2024).cbz")

    report = await rescan_series(db, settings, sid, path_override=str(alt))

    assert len(report.imported) == 1
    files = await _issue_files(db, sid)
    assert len(files) == 1  # imported into the series' own folder
