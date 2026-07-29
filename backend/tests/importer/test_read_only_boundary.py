"""The pipeline's fail-closed read-only write boundary (FRG-SER-021).

``pipeline.execute`` is the LAST line of the boundary: whatever route reaches a
real file placement for a series on a read-only reference root — a completed
download, a drain retry, a hand-built candidate — is refused before a byte is
written. The import is parked BLOCKED (an environmental refusal, not a bad
release), so nothing is lost and nothing is blocklisted.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from foragerr.downloads.models import GrabHistoryRow
from foragerr.importer.pipeline import ImportStatus, gather, import_candidate
from foragerr.importer.sources import CompletedDownloadSource
from foragerr.library.models import IssueFileRow, RootFolderRow

from importer._archives import make_cbz


async def _mark_root_read_only(db, root_folder_id: int = 1) -> None:
    async with db.write_session() as session:
        row = await session.get(RootFolderRow, root_folder_id)
        row.read_only = True


@pytest.mark.req("FRG-SER-021")
async def test_placement_under_a_read_only_root_is_refused_and_nothing_is_written(
    db, seed, import_ctx, tmp_path
):
    s = await seed()
    await _mark_root_read_only(db)
    ctx = import_ctx()
    dl_dir = tmp_path / "download" / "Example.404"
    staged = dl_dir / "Batman 404 (1987).cbz"
    make_cbz(staged)
    async with db.write_session() as session:
        session.add(
            GrabHistoryRow(
                download_id="dl-ro",
                series_id=s.series_id,
                issue_id=s.issue_id,
                title="Batman 404 (1987)",
                protocol="usenet",
                source="indexer",
                created_at=dt.datetime(2026, 7, 5),
            )
        )
    source = CompletedDownloadSource(download_id="dl-ro", output_path=str(dl_dir))

    async with db.write_session() as session:
        outcomes = [
            await import_candidate(session, candidate, ctx)
            for candidate in await gather(source, session, ctx)
        ]

    assert [o.status for o in outcomes] == [ImportStatus.BLOCKED]
    assert any("read-only" in reason for reason in outcomes[0].reasons)
    # Nothing placed under the series folder, and the staged file still exists
    # where the downloader left it (refused before the move, not after).
    assert list(s.series_path.iterdir()) == []
    assert staged.exists()
    async with db.read_session() as session:
        assert (await session.execute(select(IssueFileRow))).scalars().all() == []
