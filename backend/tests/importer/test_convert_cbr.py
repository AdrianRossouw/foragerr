"""Opt-in CBR→CBZ convert-at-import + on-demand conversion (FRG-PP-018).

The phase-2 delta scenarios, tagged:

- an enabled-policy import CONVERTS a CBR: verifies (member count + final page
  decode), swaps the ``issue_files`` row (path/size/page-count) and records a
  ``converted`` event, discarding the original;
- a default import leaves the ``.cbr`` byte-identical (no conversion, no event);
- a FAILED verification keeps the original ``.cbr`` and the import still succeeds
  (a ``convert_failed`` warning event);
- per-series on-demand conversion converts CBRs and no-ops already-CBZ files.

RAR CREATION is impossible in CI (only RARLAB's proprietary CLI writes RAR), so
the SOURCE archive is always a real vendored ``.rar`` fixture (its magic drives
the content-detected CBR path). Where an IMAGE-bearing CBR is required — which no
vendored fixture provides — the RAR-read seam (``_enumerate_members`` /
``read_image_member``) is monkeypatched to yield real PNG pages, so the rest of
the pipeline (ZIP write, member-count verify, real ``list_image_members`` +
``render_page`` decode of the produced CBZ, atomic promote, row swap, original
removal, history event) all runs for real. The failure path needs no patch at
all: a genuine text-only vendored RAR converts to a CBZ with no image pages,
which the verify honestly rejects.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.importer import convert, history
from foragerr.importer.pipeline import ImportStatus, gather, import_candidate
from foragerr.importer.sources import RescanSource
from foragerr.library import repo
from foragerr.library.models import IssueFileRow, IssueRow

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "rar"
#: A real RAR (RAR5) whose members are all TEXT — a valid, listable CBR with no
#: image pages. Converting it produces a CBZ the verify honestly rejects.
_TEXT_RAR = _FIXTURES / "rar5-subdirs.rar"


def _png(w: int = 8, h: int = 8) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (40, 90, 160)).save(buf, "PNG")
    return buf.getvalue()


def _make_cbr(path: Path) -> int:
    """Place a real vendored RAR at ``path`` (a genuine CBR by magic)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_TEXT_RAR.read_bytes())
    return path.stat().st_size


def _fake_image_rar(pages: int = 3):
    """Monkeypatch factories: make the RAR-read seam yield ``pages`` PNG members.

    ``convert._enumerate_members`` reports ``pageNNN.png`` file entries and
    ``convert.read_image_member`` returns real PNG bytes for them, so a text-only
    fixture archive is READ as an image-bearing comic — everything downstream of
    the read seam (ZIP write, verify, decode, swap) stays real."""
    names = [f"page{i:03d}.png" for i in range(pages)]
    png = _png()

    def _enum(_path, _kind):
        return [(n, False, False) for n in names]

    def _read(_path, member, *, max_bytes):
        return png

    return _enum, _read, names


#: A real RAR whose payload is a unix symlink member — inspect_archive rejects
#: it (safe_to_extract=False), the same vetting the streaming path applies.
_SYMLINK_RAR = _FIXTURES / "rar5-symlink-unix.rar"


@pytest.mark.req("FRG-OPDS-016")
def test_convert_refuses_an_unsafe_source_archive(tmp_path):
    """build_verified_cbz re-gates on inspect_archive/safe_to_extract before
    reading any member (RISK-049): a source that fails the structural vetting —
    here a real RAR carrying a symlink member — is refused with a ConvertError
    and leaves no temp CBZ behind, on the on-demand path that import-time
    gating does not cover."""
    from foragerr.importer import convert

    src = tmp_path / "evil.cbr"
    src.write_bytes(_SYMLINK_RAR.read_bytes())
    dest = tmp_path / "evil.cbz"
    with pytest.raises(convert.ConvertError):
        convert.build_verified_cbz(src, dest)
    # No temp CBZ, no destination CBZ left in the directory.
    assert not dest.exists()
    assert not list(tmp_path.glob(".foragerr-convert-*"))


async def _run(db, source, ctx) -> list:
    outcomes = []
    async with db.write_session() as session:
        for candidate in await gather(source, session, ctx):
            outcomes.append(await import_candidate(session, candidate, ctx))
    return outcomes


async def _files(db) -> list[IssueFileRow]:
    async with db.read_session() as session:
        return list((await session.execute(select(IssueFileRow))).scalars().all())


# --- Scenario: Opt-in conversion verifies before discarding (task 3.3) -------


@pytest.mark.req("FRG-PP-018")
async def test_enabled_policy_import_converts_verifies_swaps_records(
    db, seed, import_ctx, monkeypatch
):
    s = await seed()
    cbr = s.series_path / "Batman 404 (1987).cbr"
    _make_cbr(cbr)
    _enum, _read, names = _fake_image_rar(pages=3)
    monkeypatch.setattr(convert, "_enumerate_members", _enum)
    monkeypatch.setattr(convert, "read_image_member", _read)
    ctx = import_ctx(convert_cbr_to_cbz=True)

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    files = await _files(db)
    assert len(files) == 1
    row = files[0]
    placed = Path(row.path)
    # Row swapped to the .cbz: path/size/page-count all updated.
    assert placed.suffix == ".cbz"
    assert placed.exists()
    assert row.page_count == 3  # image page count of the produced CBZ
    assert row.size == placed.stat().st_size
    # The produced CBZ is a real zip with exactly the 3 verified image members.
    with zipfile.ZipFile(placed) as zf:
        assert sorted(zf.namelist()) == names
    # Original CBR discarded only AFTER verification + swap.
    assert not cbr.exists()
    assert not list(s.series_path.glob(".foragerr-convert-*"))  # temp cleaned
    # A converted history event was recorded alongside the import.
    async with db.read_session() as session:
        events = await history.events_for_issue(session, s.issue_id)
    types = [e.event_type for e in events]
    assert "imported" in types
    assert history.EVENT_CONVERTED in types


# --- Scenario: Off by default — no conversion without opt-in (task 3.3) ------


@pytest.mark.req("FRG-PP-018")
async def test_default_import_leaves_cbr_byte_identical(db, seed, import_ctx):
    s = await seed()
    cbr = s.series_path / "Batman 404 (1987).cbr"
    _make_cbr(cbr)
    original = cbr.read_bytes()
    ctx = import_ctx()  # convert_cbr_to_cbz defaults to False

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    files = await _files(db)
    assert len(files) == 1
    placed = Path(files[0].path)
    assert placed.suffix == ".cbr"  # imported as-is
    assert placed.read_bytes() == original  # byte-identical
    async with db.read_session() as session:
        events = await history.events_for_issue(session, s.issue_id)
    types = [e.event_type for e in events]
    assert history.EVENT_CONVERTED not in types
    assert history.EVENT_CONVERT_FAILED not in types


# --- Scenario: Failed verification keeps the original (task 3.4) -------------


@pytest.mark.req("FRG-PP-018")
async def test_failed_verification_keeps_original_and_import_succeeds(
    db, seed, import_ctx
):
    """A genuine text-only CBR converts to a CBZ with no image pages — the verify
    honestly rejects it, so the original .cbr is kept and the import STILL
    succeeds (no monkeypatch: the failure is real)."""
    s = await seed()
    cbr = s.series_path / "Batman 404 (1987).cbr"
    _make_cbr(cbr)
    ctx = import_ctx(convert_cbr_to_cbz=True)

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    # The import completed — a failed conversion never unwinds it.
    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    files = await _files(db)
    assert len(files) == 1
    placed = Path(files[0].path)
    assert placed.suffix == ".cbr"  # original kept as the imported file
    assert placed.exists()
    # No stray temp CBZ and no promoted .cbz was left behind.
    assert not list(s.series_path.glob(".foragerr-convert-*"))
    assert not list(s.series_path.glob("*.cbz"))
    async with db.read_session() as session:
        events = await history.events_for_issue(session, s.issue_id)
    types = [e.event_type for e in events]
    assert "imported" in types
    assert history.EVENT_CONVERT_FAILED in types
    assert history.EVENT_CONVERTED not in types


@pytest.mark.req("FRG-PP-018")
async def test_verify_decode_failure_keeps_original(db, seed, import_ctx, monkeypatch):
    """Force the image-decode half of the verify to fail (an undecodable final
    page): the original .cbr is kept and a convert_failed event recorded."""
    s = await seed()
    cbr = s.series_path / "Batman 404 (1987).cbr"
    _make_cbr(cbr)
    original = cbr.read_bytes()
    _enum, _read, _names = _fake_image_rar(pages=2)
    monkeypatch.setattr(convert, "_enumerate_members", _enum)
    monkeypatch.setattr(convert, "read_image_member", _read)

    def _boom(_data, *, max_width, max_pixels):
        raise convert.ImageRenderError("undecodable final page")

    monkeypatch.setattr(convert, "render_page", _boom)
    ctx = import_ctx(convert_cbr_to_cbz=True)

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    placed = Path((await _files(db))[0].path)
    assert placed.suffix == ".cbr"
    assert placed.read_bytes() == original
    assert not list(s.series_path.glob(".foragerr-convert-*"))
    assert not list(s.series_path.glob("*.cbz"))
    async with db.read_session() as session:
        events = await history.events_for_issue(session, s.issue_id)
    assert history.EVENT_CONVERT_FAILED in [e.event_type for e in events]


# --- Scenario: On-demand conversion per series (task 3.5) --------------------


@pytest.mark.req("FRG-PP-018")
async def test_on_demand_series_converts_cbrs_and_noops_cbzs(
    db, seed, import_ctx, monkeypatch
):
    from foragerr.importer.context import ImportContext
    from importer._archives import make_cbz

    from foragerr.library.flows.convert import convert_series

    s = await seed()
    # A second issue so the series carries two files (one CBR, one CBZ).
    async with db.write_session() as session:
        issue2 = await repo.create_issue(
            session, series_id=s.series_id, cv_issue_id=9002, issue_number="405"
        )
        issue2_id = issue2.id

    cbr = s.series_path / "Batman 404 (1987).cbr"
    _make_cbr(cbr)
    cbz = s.series_path / "Batman 405 (1987).cbz"
    make_cbz(cbz, images=2)
    cbz_original = cbz.read_bytes()

    async with db.write_session() as session:
        await repo.add_issue_file(
            session, issue_id=s.issue_id, path=str(cbr), size=cbr.stat().st_size
        )
        await repo.add_issue_file(
            session, issue_id=issue2_id, path=str(cbz), size=cbz.stat().st_size
        )

    _enum, _read, names = _fake_image_rar(pages=4)
    monkeypatch.setattr(convert, "_enumerate_members", _enum)
    monkeypatch.setattr(convert, "read_image_member", _read)

    report = await convert_series(db, None, s.series_id)

    # The CBR converted (verify-before-discard); the CBZ was skipped as a no-op.
    assert len(report.converted) == 1
    assert report.skipped == 1
    assert report.failed == 0
    assert not cbr.exists()
    converted = s.series_path / "Batman 404 (1987).cbz"
    assert converted.exists()
    assert cbz.read_bytes() == cbz_original  # the already-CBZ file untouched

    async with db.read_session() as session:
        rows = list((await session.execute(select(IssueFileRow))).scalars().all())
    by_issue = {r.issue_id: r for r in rows}
    assert by_issue[s.issue_id].path == str(converted)
    assert by_issue[s.issue_id].page_count == 4
    assert by_issue[issue2_id].path == str(cbz)  # unchanged
    # A converted event for the CBR; the CBZ no-op recorded nothing.
    async with db.read_session() as session:
        cbr_events = await history.events_for_issue(session, s.issue_id)
        cbz_events = await history.events_for_issue(session, issue2_id)
    assert history.EVENT_CONVERTED in [e.event_type for e in cbr_events]
    assert cbz_events == []


# --- TODO(owner-fixture): comic-shaped image-bearing .cbr ---------------------


@pytest.mark.req("FRG-PP-018")
@pytest.mark.skip(
    reason="TODO(owner-fixture): needs a comic-shaped image-bearing .cbr (RAR4+RAR5 "
    "with real PNG/JPEG pages) to exercise the convert-at-import path end-to-end "
    "through the REAL rarfile/unrar read seam. RAR creation is impossible in CI; "
    "the owner generates these with RARLAB's macOS-arm trial CLI on his host. Until "
    "then the read seam is monkeypatched (see _fake_image_rar) while the ZIP write, "
    "member-count verify, real render_page decode, atomic swap and history event "
    "all run for real; this stub records the residual real-.cbr coverage gap."
)
async def test_convert_real_image_cbr_end_to_end() -> None:  # pragma: no cover
    raise AssertionError("owner-fixture stub — never runs")
