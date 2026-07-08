"""OPDS-PSE page-count producer (FRG-OPDS-009): the import pipeline caches the
archive's image-page count on ``issue_files.page_count`` from the report it
already produced — no extra archive open. A listable CBZ gets ``image_count``; an
unlistable archive (a magic-only CBR with ``rarfile`` absent) stays ``NULL``. The
column also round-trips a written value straight through the ORM."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from foragerr.importer.pipeline import ImportStatus, gather, import_candidate
from foragerr.importer.sources import RescanSource
from foragerr.library.models import IssueFileRow

from importer._archives import make_cbz

# RAR magic so inspect_archive detects a CBR; with rarfile absent the report is
# ok=True but listed=False (magic-only) — exactly the "unlistable" producer branch.
_RAR_MAGIC = b"Rar!\x1a\x07\x00"


async def _run(db, source, ctx):
    outcomes = []
    async with db.write_session() as session:
        for candidate in await gather(source, session, ctx):
            outcomes.append(await import_candidate(session, candidate, ctx))
    return outcomes


@pytest.mark.req("FRG-OPDS-009")
async def test_listable_cbz_import_caches_image_count(db, seed, import_ctx):
    """An imported real CBZ row carries page_count == the archive's image_count,
    populated from the report the pipeline already produced (no extra open)."""
    s = await seed()
    make_cbz(s.series_path / "Batman 404 (1987).cbz", images=5)
    ctx = import_ctx()

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    async with db.read_session() as session:
        row = (await session.execute(select(IssueFileRow))).scalar_one()
    assert row.page_count == 5  # == image_count for the 5-image cbz


@pytest.mark.req("FRG-OPDS-009")
async def test_unlistable_cbr_import_leaves_page_count_null(db, seed, import_ctx):
    """A magic-only CBR (rarfile absent → report.listed=False) imports but its
    page_count stays NULL — no PSE, resolved lazily later if ever listable."""
    s = await seed()
    cbr = s.series_path / "Batman 404 (1987).cbr"
    cbr.write_bytes(_RAR_MAGIC + b"\x00" * 256)  # > junk floor, valid RAR magic
    ctx = import_ctx()

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    async with db.read_session() as session:
        row = (await session.execute(select(IssueFileRow))).scalar_one()
    assert row.page_count is None


@pytest.mark.req("FRG-OPDS-009")
async def test_listed_cbr_import_still_leaves_page_count_null(
    db, seed, import_ctx, monkeypatch
):
    """FIX-1a: even a CBR that ``rarfile`` DID enumerate (report.listed=True,
    kind='rar', image_count>0) must leave page_count NULL. The OPDS page reader is
    zip-only, so advertising PSE for a non-zip archive would 404 every page —
    listability alone must not gate the producer; the container kind must be zip."""
    from foragerr.importer import pipeline as pl
    from foragerr.security.archives import ArchiveReport

    s = await seed()
    cbr = s.series_path / "Batman 404 (1987).cbr"
    cbr.write_bytes(_RAR_MAGIC + b"\x00" * 256)
    ctx = import_ctx()

    real_inspect = pl.inspect_archive

    def _fake_inspect(path, *args, **kwargs):
        report = real_inspect(path, *args, **kwargs)
        if report.kind == "rar":
            # Simulate rarfile present and successfully listing the CBR's members.
            return ArchiveReport(
                ok=True, kind="rar", member_count=7, image_count=7,
                listed=True, safe_to_extract=True,
            )
        return report

    monkeypatch.setattr(pl, "inspect_archive", _fake_inspect)

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    async with db.read_session() as session:
        row = (await session.execute(select(IssueFileRow))).scalar_one()
    assert row.page_count is None  # listed rar, but not zip → no PSE count


@pytest.mark.req("FRG-OPDS-009")
async def test_page_count_column_round_trips(db, seed):
    """The nullable column round-trips a written value straight through the ORM."""
    s = await seed()
    async with db.write_session() as session:
        session.add(
            IssueFileRow(
                issue_id=s.issue_id,
                path=str(s.series_path / "a.cbz"),
                size=10,
                added_at=dt.datetime(2026, 7, 5),
                page_count=17,
            )
        )
    async with db.read_session() as session:
        row = (await session.execute(select(IssueFileRow))).scalar_one()
    assert row.page_count == 17
