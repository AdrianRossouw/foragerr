"""The pipeline's fail-closed read-only write boundary (FRG-SER-021).

``pipeline.execute`` is the LAST line of the boundary: whatever route reaches a
real file placement — or a disposal, or a post-placement archive rewrite — for a
series on a read-only reference root is refused before a byte is written. The
import is parked BLOCKED (an environmental refusal, not a bad release), so
nothing is lost and nothing is blocklisted.

Three directions are covered here, because the destination series' root answers
only the first:

* the DESTINATION lands under a read-only root (a download, a drain retry);
* the CANDIDATE's own file already lives under one and move mode would take it
  away (a manual pick, a rescan override);
* the file is registered in place and a POST-placement rewrite (ComicInfo
  tagging, CBR→CBZ conversion) would edit the operator's original.

The read-only flag is set on a perfectly writable temp directory on purpose: a
passing assertion then means foragerr chose not to write, not that the
filesystem stopped it.
"""

from __future__ import annotations

import datetime as dt
import zipfile

import pytest
from sqlalchemy import select

from foragerr.downloads.models import GrabHistoryRow
from foragerr.importer import fileops
from foragerr.importer.pipeline import ImportStatus, gather, import_candidate
from foragerr.importer.sources import (
    SOURCE_LIBRARY,
    SOURCE_MANUAL,
    CompletedDownloadSource,
    ImportCandidate,
    ManualOverride,
)
from foragerr.library.models import IssueFileRow, RootFolderRow

from importer._archives import make_cbz


async def _mark_root_read_only(db, root_folder_id: int = 1) -> None:
    async with db.write_session() as session:
        row = await session.get(RootFolderRow, root_folder_id)
        row.read_only = True


async def _add_read_only_root(db, path) -> int:
    from foragerr.library import repo

    async with db.write_session() as session:
        row = await repo.create_root_folder(session, str(path), read_only=True)
        return row.id


def _stat(path) -> tuple[int, int, int]:
    """``(inode, size, mtime_ns)`` — any rewrite of the file changes at least
    one of them, so comparing before/after proves the bytes were left alone."""
    info = path.stat()
    return (info.st_ino, info.st_size, info.st_mtime_ns)


@pytest.mark.req("FRG-SER-021")
def test_one_policy_raises_exactly_one_exception_type():
    """The pipeline used to raise its own refusal type for the same policy, and
    only the boundary module's type is registered with the uniform 409 handler —
    so a second type reaching any request path would surface as a 500. Pinned by
    identity: the pipeline refuses with the registered type, not a sibling."""
    from fastapi import FastAPI

    from foragerr.api.errors import register_error_handlers
    from foragerr.importer import pipeline
    from foragerr.library.read_only import ReadOnlySeriesError

    app = FastAPI()
    register_error_handlers(app)
    assert ReadOnlySeriesError in app.exception_handlers
    assert pipeline.ReadOnlySeriesError is ReadOnlySeriesError
    assert not [
        name
        for name, obj in vars(pipeline).items()
        if isinstance(obj, type)
        and issubclass(obj, Exception)
        and "readonly" in name.casefold()
        and obj is not ReadOnlySeriesError
    ]


@pytest.mark.req("FRG-SER-021")
async def test_placement_under_a_read_only_root_is_refused_and_nothing_is_written(
    db, seed, import_ctx, tmp_path
):
    s = await seed()
    await _mark_root_read_only(db)
    ctx = import_ctx()
    dl_dir = tmp_path / "download" / "Example.404"
    staged = dl_dir / "Example Series 404 (1987).cbz"
    make_cbz(staged)
    async with db.write_session() as session:
        session.add(
            GrabHistoryRow(
                download_id="dl-ro",
                series_id=s.series_id,
                issue_id=s.issue_id,
                title="Example Series 404 (1987)",
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


@pytest.mark.req("FRG-SER-021")
async def test_moving_a_file_out_of_a_read_only_root_is_refused(
    db, seed, import_ctx, tmp_path
):
    """The SOURCE side of the boundary. The destination series here is on a
    perfectly writable root, so every guard that asks "is the target read-only?"
    answers no — but the file being imported is one of the operator's originals,
    and move mode places it with an ``os.replace`` that removes it from the
    reference library. Refused on the candidate's own location, whatever the
    destination."""
    s = await seed()
    reference = tmp_path / "reference-library"
    original = reference / "example series v1" / "Example Series 404 (1987).cbz"
    make_cbz(original)
    await _add_read_only_root(db, reference)
    ctx = import_ctx(transfer_mode=fileops.TransferMode.MOVE)
    before = _stat(original)
    candidate = ImportCandidate(
        source_kind=SOURCE_MANUAL,
        local_path=str(original),
        size=original.stat().st_size,
        file_name=original.name,
        folder_name=original.parent.name,
        container_root=str(original.parent),
        override=ManualOverride(series_id=s.series_id, issue_id=s.issue_id),
    )

    async with db.write_session() as session:
        outcome = await import_candidate(session, candidate, ctx)

    assert outcome.status is ImportStatus.BLOCKED
    assert any("read-only" in reason for reason in outcome.reasons)
    assert original.exists() and _stat(original) == before
    assert list(s.series_path.iterdir()) == []
    async with db.read_session() as session:
        assert (await session.execute(select(IssueFileRow))).scalars().all() == []


@pytest.mark.req("FRG-SER-021")
@pytest.mark.req("FRG-PP-017")
@pytest.mark.req("FRG-PP-018")
async def test_an_in_place_registration_never_rewrites_the_archive(
    db, seed, import_ctx
):
    """The two POST-placement rewrites are not covered by the placement guard.

    ComicInfo tagging and CBR→CBZ conversion run AFTER a successful import, on
    the file the import registered — which for an index-in-place import IS the
    operator's original inside the read-only library. The library-import flow
    forces both toggles off, but this drives the pipeline DIRECTLY with them on,
    so the write sites have to refuse on their own: the registration succeeds
    and the archive comes out byte-identical, still carrying no ComicInfo."""
    s = await seed()
    await _mark_root_read_only(db)
    original = s.series_path / "Example Series 404 (1987).cbz"
    make_cbz(original)
    before = _stat(original)
    ctx = import_ctx(
        library_import_mode="in_place",
        rename_enabled=False,
        comicinfo_tag_enabled=True,
        convert_cbr_to_cbz=True,
    )
    candidate = ImportCandidate(
        source_kind=SOURCE_LIBRARY,
        local_path=str(original),
        size=original.stat().st_size,
        file_name=original.name,
        folder_name=original.parent.name,
        container_root=str(s.series_path),
        series_scope_id=s.series_id,
        override=ManualOverride(series_id=s.series_id),
    )

    async with db.write_session() as session:
        outcome = await import_candidate(session, candidate, ctx)

    assert outcome.status is ImportStatus.IMPORTED
    assert outcome.imported_path == str(original)
    assert _stat(original) == before  # not one byte rewritten
    with zipfile.ZipFile(original) as zf:
        assert "ComicInfo.xml" not in zf.namelist()
