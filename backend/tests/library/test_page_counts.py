"""Lazy OPDS-PSE page-count resolution + write-back + size-mismatch
invalidation (FRG-OPDS-009). ``resolve_page_count`` is the first-access fallback
for NULL rows: it computes the count from the archive's image members, writes it
back, and trusts the cache only while the stored ``size`` still matches the file
on disk — a mismatch forces a recompute (a cheap content-change guard)."""

from __future__ import annotations

import datetime as dt
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.library import repo
from foragerr.library.models import IssueFileRow
from foragerr.library.page_counts import resolve_page_count

# A genuine 1x1 PNG so each member is a real image entry.
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f9f0000000049454e44ae42"
    "6082"
)


def _make_cbz(path: Path, *, images: int) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for i in range(images):
            zf.writestr(f"page{i:03d}.png", _PNG_1x1)
    return path.stat().st_size


async def _seed_issue_file(db, root_folder_id, format_profile_id, *, path, size):
    """Create a series+issue+issue_file (page_count NULL) and return its id."""
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=42,
            title="Batman",
            start_year=1987,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/Batman",
        )
        issue = await repo.create_issue(
            session, series_id=series.id, cv_issue_id=9001, issue_number="404"
        )
        row = await repo.add_issue_file(
            session, issue_id=issue.id, path=path, size=size,
            added_at=dt.datetime(2026, 7, 5),
        )
        return row.id


@pytest.mark.req("FRG-OPDS-009")
async def test_null_count_computed_and_written_on_first_access(
    db, tmp_path, root_folder_id, format_profile_id
):
    cbz = tmp_path / "b.cbz"
    size = _make_cbz(cbz, images=3)
    file_id = await _seed_issue_file(
        db, root_folder_id, format_profile_id, path=str(cbz), size=size
    )

    async with db.write_session() as session:
        row = await session.get(IssueFileRow, file_id)
        assert row.page_count is None
        count = await resolve_page_count(session, row, cbz)
        assert count == 3
        assert row.page_count == 3  # written back onto the row

    async with db.read_session() as session:
        assert (await session.get(IssueFileRow, file_id)).page_count == 3


@pytest.mark.req("FRG-OPDS-009")
async def test_cached_count_returned_without_recompute_when_size_unchanged(
    db, tmp_path, root_folder_id, format_profile_id
):
    cbz = tmp_path / "b.cbz"
    size = _make_cbz(cbz, images=3)
    file_id = await _seed_issue_file(
        db, root_folder_id, format_profile_id, path=str(cbz), size=size
    )

    async with db.write_session() as session:
        row = await session.get(IssueFileRow, file_id)
        # A cached count that disagrees with the archive's real 3 pages: if it is
        # returned verbatim, the archive was never opened (the no-I/O guarantee).
        row.page_count = 99
        await session.flush()
        count = await resolve_page_count(session, row, cbz)
        assert count == 99


@pytest.mark.req("FRG-OPDS-009")
async def test_size_mismatch_forces_recompute(
    db, tmp_path, root_folder_id, format_profile_id
):
    cbz = tmp_path / "b.cbz"
    _make_cbz(cbz, images=3)
    # Seed a STALE size that no longer matches the file on disk.
    file_id = await _seed_issue_file(
        db, root_folder_id, format_profile_id, path=str(cbz), size=1
    )

    async with db.write_session() as session:
        row = await session.get(IssueFileRow, file_id)
        row.page_count = 99  # stale cached count
        await session.flush()
        count = await resolve_page_count(session, row, cbz)
        assert count == 3  # recomputed from the actual archive
        assert row.page_count == 3
        assert row.size == cbz.stat().st_size  # invalidation key refreshed
        assert row.path == str(cbz)  # path is never rewritten


@pytest.mark.req("FRG-OPDS-009")
async def test_unlistable_archive_resolves_to_none(
    db, tmp_path, root_folder_id, format_profile_id
):
    """A magic-only CBR (rarfile absent) is not listable → resolve returns None
    and the row's page_count stays NULL (no PSE)."""
    cbr = tmp_path / "b.cbr"
    cbr.write_bytes(b"Rar!\x1a\x07\x00" + b"\x00" * 256)
    file_id = await _seed_issue_file(
        db, root_folder_id, format_profile_id, path=str(cbr),
        size=cbr.stat().st_size,
    )

    async with db.write_session() as session:
        row = await session.get(IssueFileRow, file_id)
        count = await resolve_page_count(session, row, cbr)
        assert count is None
        assert row.page_count is None
