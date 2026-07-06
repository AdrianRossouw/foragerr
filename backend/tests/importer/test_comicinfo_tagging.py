"""ComicInfo.xml write-on-import (FRG-PP-017, write half).

Every delta scenario of the FRG-PP-017 block, tagged: an enabled tag writes a
schema-valid ComicInfo.xml built from the library record (parsed back through the
hardened untrusted-XML site to assert fields); disabled leaves the archive
byte-identical; a hostile member name is refused by both the ``safe_to_extract``
gate and the streaming re-check; an oversized member is bounded (degrades to a
warning); and a rewrite that raises partway leaves the placed file byte-identical
+ imported, records a ``comicinfo_tag_failed`` warning, and never fails the import.
"""

from __future__ import annotations

import datetime as dt
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.importer import history, pipeline
from foragerr.importer.pipeline import ImportStatus, gather, import_candidate
from foragerr.importer.sources import RescanSource
from foragerr.indexers.xml import parse_untrusted_xml
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow
from foragerr.metadata import comicinfo
from foragerr.metadata.comicinfo import (
    COMICINFO_MAX_BYTES,
    ComicInfoTagError,
    tag_cbz,
)
from foragerr.security.archives import inspect_archive

from importer._archives import comicinfo_xml, make_cbz, make_cbz_with_comicinfo


async def _run(db, source, ctx) -> list:
    """gather → import_candidate for one source; returns the outcomes."""
    outcomes = []
    async with db.write_session() as session:
        for candidate in await gather(source, session, ctx):
            outcomes.append(await import_candidate(session, candidate, ctx))
    return outcomes


async def _enrich(db, s) -> None:
    """Fill the seeded series/issue with the metadata the tag renders."""
    async with db.write_session() as session:
        series = await session.get(SeriesRow, s.series_id)
        issue = await session.get(IssueRow, s.issue_id)
        series.publisher = "DC Comics"
        issue.title = "Batman: Year Three"
        issue.cover_date = dt.date(1987, 2, 15)


async def _placed_path(db) -> Path:
    async with db.read_session() as session:
        files = (await session.execute(select(IssueFileRow))).scalars().all()
    assert len(files) == 1
    return Path(files[0].path)


def _read_member(path: Path, name: str = "ComicInfo.xml") -> bytes:
    with zipfile.ZipFile(path) as zf:
        return zf.read(name)


def _no_temp_left(folder: Path) -> bool:
    return not list(folder.glob(".foragerr-comicinfo-*"))


# --- Scenario: Enabled tagging writes a schema-valid ComicInfo.xml -----------


@pytest.mark.req("FRG-PP-017")
async def test_enabled_tagging_writes_schema_valid_comicinfo(db, seed, import_ctx):
    s = await seed()
    await _enrich(db, s)
    make_cbz(s.series_path / "Batman 404 (1987).cbz")
    ctx = import_ctx(comicinfo_tag_enabled=True)

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    placed = await _placed_path(db)
    # Exactly one root-level ComicInfo.xml member was written.
    with zipfile.ZipFile(placed) as zf:
        assert [n for n in zf.namelist() if n.lower() == "comicinfo.xml"] == [
            "ComicInfo.xml"
        ]
    # Parse the written member back through the HARDENED untrusted-XML site and
    # assert every field came from the library record.
    root = parse_untrusted_xml(_read_member(placed), max_bytes=COMICINFO_MAX_BYTES)
    assert root.findtext("Series") == "Batman"
    assert root.findtext("Number") == s.issue_number
    assert root.findtext("Title") == "Batman: Year Three"
    assert root.findtext("Volume") == "1987"
    assert root.findtext("Year") == "1987"
    assert root.findtext("Month") == "2"
    assert root.findtext("Day") == "15"
    assert root.findtext("Publisher") == "DC Comics"
    assert f"4000-{s.cv_issue_id}" in (root.findtext("Web") or "")
    assert _no_temp_left(s.series_path)
    # The import otherwise proceeded normally — a plain imported event.
    async with db.read_session() as session:
        events = await history.events_for_issue(session, s.issue_id)
    assert [e.event_type for e in events] == ["imported"]


# --- Scenario: Disabled tagging leaves the archive untouched -----------------


@pytest.mark.req("FRG-PP-017")
async def test_disabled_tagging_leaves_archive_byte_identical(db, seed, import_ctx):
    s = await seed()
    src = s.series_path / "Batman 404 (1987).cbz"
    make_cbz(src)
    original = src.read_bytes()
    ctx = import_ctx()  # comicinfo_tag_enabled defaults to False

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    placed = await _placed_path(db)
    assert placed.read_bytes() == original  # no rewrite happened at all
    with zipfile.ZipFile(placed) as zf:
        assert not [n for n in zf.namelist() if n.lower() == "comicinfo.xml"]
    assert _no_temp_left(s.series_path)


# --- Scenario: Hostile member name in the source cbz -------------------------


@pytest.mark.req("FRG-PP-017")
def test_hostile_member_name_defeats_safe_to_extract_gate(tmp_path: Path):
    """The inspection gate: a traversal member makes ``safe_to_extract`` false, so
    the pipeline never even attempts a rewrite."""
    cbz = tmp_path / "hostile.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        zf.writestr("page000.png", b"\x89PNG\r\n\x1a\n")
        zf.writestr("../escape.txt", b"pwned")
    report = inspect_archive(str(cbz))
    assert report.ok is False
    assert report.safe_to_extract is False


@pytest.mark.req("FRG-PP-017")
def test_hostile_member_name_refused_by_streaming_recheck(tmp_path: Path):
    """Defense in depth: even handed a zip whose member escapes, the streaming
    rewrite re-checks each name, refuses, and leaves the file byte-identical."""
    cbz = tmp_path / "hostile.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        zf.writestr("page000.png", b"\x89PNG\r\n\x1a\n")
        zf.writestr("../escape.png", b"pwned")
    original = cbz.read_bytes()

    with pytest.raises(ComicInfoTagError):
        tag_cbz(str(cbz), b"<ComicInfo><Series>X</Series></ComicInfo>")

    assert cbz.read_bytes() == original  # untouched
    assert _no_temp_left(tmp_path)  # temp unlinked
    # No traversed file was ever written outside the archive.
    assert not (tmp_path.parent / "escape.png").exists()


# --- Scenario: Oversized ComicInfo source metadata is bounded ----------------


@pytest.mark.req("FRG-PP-017")
async def test_oversized_existing_comicinfo_is_bounded(db, seed, import_ctx):
    s = await seed()
    await _enrich(db, s)
    src = s.series_path / "Batman 404 (1987).cbz"
    # An existing ComicInfo.xml declaring more than the dedicated 1 MiB cap.
    make_cbz_with_comicinfo(
        src, xml=comicinfo_xml(pad_bytes=COMICINFO_MAX_BYTES + 4096)
    )
    original = src.read_bytes()
    ctx = import_ctx(comicinfo_tag_enabled=True)

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    # The import still SUCCEEDS — tagging is best-effort after placement.
    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    placed = await _placed_path(db)
    assert placed.read_bytes() == original  # left byte-identical (rewrite refused)
    assert _no_temp_left(s.series_path)
    async with db.read_session() as session:
        events = await history.events_for_issue(session, s.issue_id)
    types = [e.event_type for e in events]
    assert "imported" in types
    assert history.EVENT_COMICINFO_TAG_FAILED in types


@pytest.mark.req("FRG-PP-017")
def test_oversized_generic_member_is_bounded(tmp_path: Path):
    """A non-ComicInfo member declaring over the per-member cap is refused BEFORE
    any read (bounded), leaving the file byte-identical."""
    cbz = tmp_path / "big.cbz"
    make_cbz(cbz, images=1)
    original = cbz.read_bytes()

    with pytest.raises(ComicInfoTagError):
        # A tiny cap turns the ordinary page member into an over-cap member.
        tag_cbz(
            str(cbz),
            b"<ComicInfo><Series>X</Series></ComicInfo>",
            max_member_bytes=1,
        )

    assert cbz.read_bytes() == original
    assert _no_temp_left(tmp_path)


# --- Scenario: Rewrite failure leaves the original intact --------------------


@pytest.mark.req("FRG-PP-017")
async def test_rewrite_failure_leaves_original_and_still_imports(
    db, seed, import_ctx, monkeypatch
):
    s = await seed()
    await _enrich(db, s)
    src = s.series_path / "Batman 404 (1987).cbz"
    make_cbz(src)
    original = src.read_bytes()
    ctx = import_ctx(comicinfo_tag_enabled=True)

    # Inject a failure PARTWAY through the rewrite: the temp zip is fully written,
    # then the fsync-before-atomic-replace raises. os.fsync is not on the
    # same-device place_file path, so only the tag rewrite is affected.
    def _boom(_fd):
        raise OSError("disk full during fsync")

    monkeypatch.setattr(comicinfo.os, "fsync", _boom)

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    # The import completed; the tag failure did NOT unwind or fail it.
    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    placed = await _placed_path(db)
    assert placed.read_bytes() == original  # byte-identical, untagged
    assert _no_temp_left(s.series_path)  # the partial temp was unlinked
    async with db.read_session() as session:
        events = await history.events_for_issue(session, s.issue_id)
    types = [e.event_type for e in events]
    assert "imported" in types
    assert history.EVENT_COMICINFO_TAG_FAILED in types


@pytest.mark.req("FRG-PP-017")
async def test_db_error_during_tagging_leaves_import_committed(
    db, seed, import_ctx, monkeypatch
):
    """Tagging is best-effort AFTER the import commits: a non-IO error while
    building the tag (e.g. a DB error loading records) must NOT unwind the
    completed import — it lands untagged with a warning event (regression: the
    narrow catch let it escape and roll the import back to BLOCKED)."""
    s = await seed()
    await _enrich(db, s)
    make_cbz(s.series_path / "Batman 404 (1987).cbz")
    ctx = import_ctx(comicinfo_tag_enabled=True)

    def _boom(series, issue):
        raise RuntimeError("db connection lost while building the tag")

    monkeypatch.setattr(pipeline, "build_comicinfo_bytes", _boom)

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    async with db.read_session() as session:
        events = await history.events_for_issue(session, s.issue_id)
    types = [e.event_type for e in events]
    assert "imported" in types
    assert history.EVENT_COMICINFO_TAG_FAILED in types


@pytest.mark.req("FRG-PP-017")
def test_tag_cbz_propagates_cancellation_after_cleanup(tmp_path, monkeypatch):
    """Cleanup must not swallow cancellation/shutdown: a ``KeyboardInterrupt`` (a
    BaseException, not Exception) raised mid-rewrite is re-raised after the temp is
    unlinked, not wrapped as a ``ComicInfoTagError`` (regression)."""
    cbz = tmp_path / "c.cbz"
    make_cbz(cbz)
    original = cbz.read_bytes()

    def _boom(_src, _dst):
        raise KeyboardInterrupt

    monkeypatch.setattr(comicinfo.os, "replace", _boom)

    with pytest.raises(KeyboardInterrupt):
        tag_cbz(str(cbz), b"<ComicInfo><Series>X</Series></ComicInfo>")

    assert cbz.read_bytes() == original  # untouched
    assert _no_temp_left(tmp_path)  # temp still cleaned up before re-raising


@pytest.mark.req("FRG-PP-017")
def test_tag_cbz_primitive_cleans_temp_on_replace_failure(tmp_path, monkeypatch):
    """The rewrite primitive unlinks its temp and leaves the source byte-identical
    when the atomic replace itself fails."""
    cbz = tmp_path / "c.cbz"
    make_cbz(cbz)
    original = cbz.read_bytes()

    def _boom(_src, _dst):
        raise OSError("replace failed")

    monkeypatch.setattr(comicinfo.os, "replace", _boom)

    with pytest.raises(ComicInfoTagError):
        tag_cbz(str(cbz), b"<ComicInfo><Series>X</Series></ComicInfo>")

    assert cbz.read_bytes() == original
    assert _no_temp_left(tmp_path)
