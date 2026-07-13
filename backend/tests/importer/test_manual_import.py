"""Manual import + embedded-metadata reconciliation through the shared pipeline
(FRG-PP-016, FRG-IMP-024, FRG-API-015 execution safety).

Every test drives the SAME ``gather → import_candidate`` path automatic import
uses — a :class:`ManualImportSource` and per-file :class:`ManualOverride`s are the
only difference, and the full ``default_specs()`` set always runs.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from foragerr.db import utcnow
from foragerr.downloads.manual_import import (
    ManualFileSpec,
    execute_manual_import,
    list_manual_candidates,
)
from foragerr.downloads.models import GrabHistoryRow, TrackedDownloadRow
from foragerr.importer import (
    CompletedDownloadSource,
    ImportStatus,
    ManualImportSource,
    ManualOverride,
    RescanSource,
    history,
    import_candidate,
)
from foragerr.importer.pipeline import gather
from foragerr.library import repo
from foragerr.library.models import IssueFileRow
from foragerr.naming import RenameFields, render_filename

_CVID_TEMPLATE = "{Series Title} {Issue Number:000} ({Year}) {CvIssueId}"

from importer._archives import (
    comicinfo_xml,
    make_cbz,
    make_cbz_with_comicinfo,
    make_corrupt,
)


async def _run(db, source, ctx):
    outcomes = []
    async with db.write_session() as session:
        for candidate in await gather(source, session, ctx):
            outcomes.append(await import_candidate(session, candidate, ctx))
    return outcomes


async def _add_grab(db, *, download_id, series_id, issue_id, title):
    async with db.write_session() as session:
        session.add(
            GrabHistoryRow(
                download_id=download_id,
                series_id=series_id,
                issue_id=issue_id,
                title=title,
                protocol="usenet",
                source="indexer",
                created_at=dt.datetime(2026, 7, 5),
            )
        )


async def _issue_files(db):
    async with db.read_session() as session:
        return (await session.execute(select(IssueFileRow))).scalars().all()


async def _add_issue(db, series_id, *, cv_issue_id, issue_number):
    async with db.write_session() as session:
        issue = await repo.create_issue(
            session,
            series_id=series_id,
            cv_issue_id=cv_issue_id,
            issue_number=issue_number,
        )
        return issue.id


# --- FRG-IMP-024: embedded read reconciliation ------------------------------


@pytest.mark.req("FRG-IMP-024")
async def test_verified_embedded_id_beats_a_misleading_filename(
    db, seed, import_ctx, tmp_path
):
    s = await seed(title="Batman", issue_number="404", cv_issue_id=9001)
    # A second real issue the filename would otherwise resolve to.
    id_405 = await _add_issue(db, s.series_id, cv_issue_id=9002, issue_number="405")
    ctx = import_ctx()

    dl = tmp_path / "dl"
    # Filename parses cleanly to issue 405, but the embedded CV id points at 404.
    make_cbz_with_comicinfo(
        dl / "Batman 405 (1987).cbz", xml=comicinfo_xml(cv_issue_id=9001)
    )
    outcomes = await _run(
        db, CompletedDownloadSource(download_id="dl-1", output_path=str(dl)), ctx
    )

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    # The verified embedded id won: imported to 404, not the filename's 405.
    assert outcomes[0].issue_id == s.issue_id
    assert outcomes[0].issue_id != id_405
    async with db.read_session() as session:
        events = await history.events_for_issue(session, s.issue_id)
    data = history.decode_data(events[0].data)
    assert data["provenance"]["issue"] == "comicinfo"


@pytest.mark.req("FRG-IMP-024")
async def test_conflicting_embedded_id_surfaces_as_review_item(db, seed, import_ctx):
    superman = await seed(
        title="Superman", issue_number="1", cv_volume_id=100, cv_issue_id=8001
    )
    await seed(title="Batman", issue_number="404", cv_volume_id=42, cv_issue_id=9001)
    ctx = import_ctx()

    # Dropped into Superman's folder, filename matches Superman #1, but the
    # embedded id points at a Batman issue (another series) — a conflict.
    make_cbz_with_comicinfo(
        superman.series_path / "Superman 001 (2011).cbz",
        xml=comicinfo_xml(series="Batman", number="404", cv_issue_id=9001),
    )
    outcomes = await _run(db, RescanSource(series_id=superman.series_id), ctx)

    assert [o.status for o in outcomes] == [ImportStatus.BLOCKED]
    assert any("conflicts" in r for r in outcomes[0].reasons)
    assert await _issue_files(db) == []  # not silently mis-filed


@pytest.mark.req("FRG-IMP-024")
async def test_unresolvable_embedded_id_falls_back_to_heuristic(
    db, seed, import_ctx, tmp_path
):
    s = await seed(title="Batman", issue_number="404", cv_issue_id=9001)
    ctx = import_ctx()
    dl = tmp_path / "dl"
    # Embedded id is for an issue we do not have; filename resolves fine.
    make_cbz_with_comicinfo(
        dl / "Batman 404 (1987).cbz", xml=comicinfo_xml(cv_issue_id=123456)
    )
    outcomes = await _run(
        db, CompletedDownloadSource(download_id="dl-1", output_path=str(dl)), ctx
    )
    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert outcomes[0].issue_id == s.issue_id


@pytest.mark.req("FRG-IMP-024")
async def test_malformed_comicinfo_never_crashes_pipeline(
    db, seed, import_ctx, tmp_path
):
    s = await seed(title="Batman", issue_number="404", cv_issue_id=9001)
    ctx = import_ctx()
    dl = tmp_path / "dl"
    make_cbz_with_comicinfo(dl / "Batman 404 (1987).cbz", xml="<ComicInfo><Series>x")
    outcomes = await _run(
        db, CompletedDownloadSource(download_id="dl-1", output_path=str(dl)), ctx
    )
    # Degrades to filename evidence; imports normally, never raises.
    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert outcomes[0].issue_id == s.issue_id


@pytest.mark.req("FRG-IMP-024")
async def test_oversized_comicinfo_pipeline_imports_on_filename(
    db, seed, import_ctx, tmp_path
):
    s = await seed(title="Batman", issue_number="404", cv_issue_id=9001)
    ctx = import_ctx()
    dl = tmp_path / "dl"
    make_cbz_with_comicinfo(
        dl / "Batman 404 (1987).cbz",
        xml=comicinfo_xml(cv_issue_id=9001, pad_bytes=2 * 1024 * 1024),
    )
    outcomes = await _run(
        db, CompletedDownloadSource(download_id="dl-1", output_path=str(dl)), ctx
    )
    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert outcomes[0].issue_id == s.issue_id


# --- FRG-PP-009: the durable [cvid-<ID>] filename tag feeds the cv namespace ---


@pytest.mark.req("FRG-PP-009")
async def test_cvid_filename_tag_resolves_via_cv_namespace_after_reinstall(
    db, seed, import_ctx, tmp_path
):
    """A ``[cvid-<ID>]`` tag rendered by ``{CvIssueId}`` resolves to the right
    issue by ComicVine id even when internal row ids differ from the cv ids and
    the filename number is misleading — the reinstall-survival contract.

    Two real issues get internal row ids in insertion order, unrelated to their
    ComicVine ids (exactly the post-reinstall / clean-slate state where an
    internal-row-id ``[__id__]`` tag would silently mis-map). The name is rendered
    for cv 9001 (#404) but deliberately misstates the issue number as 405, so only
    the cvid tag — fed into the EXISTING cv-issue-id namespace — can pin #404.
    """
    s = await seed(title="Batman", issue_number="404", cv_issue_id=9001)
    id_405 = await _add_issue(db, s.series_id, cv_issue_id=9002, issue_number="405")
    ctx = import_ctx()

    dl = tmp_path / "dl"
    fields = RenameFields(
        series_title="Batman",
        issue="405",  # misleading: the filename heuristic alone would pick #405
        year="1987",
        cv_issue_id=str(s.cv_issue_id),  # durable identity → #404
    )
    name = render_filename(fields, template=_CVID_TEMPLATE, ext=".cbz")
    assert "[cvid-9001]" in name
    make_cbz(dl / name)

    outcomes = await _run(
        db, CompletedDownloadSource(download_id="dl-1", output_path=str(dl)), ctx
    )

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    # Resolved by cv id to #404, NOT the filename's #405, regardless of row ids.
    assert outcomes[0].issue_id == s.issue_id
    assert outcomes[0].issue_id != id_405
    async with db.read_session() as session:
        events = await history.events_for_issue(session, s.issue_id)
    data = history.decode_data(events[0].data)
    # It went through the cv-issue-id namespace, not the filename heuristic.
    assert data["provenance"]["issue"] == "comicinfo"


# --- FRG-IMP-024: our own signals (tag / grab) outrank the embedded id -------


@pytest.mark.req("FRG-IMP-024")
async def test_grabbed_download_ignores_misleading_embedded_id(
    db, seed, import_ctx, tmp_path
):
    """An automatic download with authoritative grab hints imports to the GRABBED
    issue — a stray embedded id neither overrides it nor blocks it. The embedded
    layer sits BELOW our own grab record (regression: it used to override)."""
    s = await seed(title="Batman", issue_number="404", cv_issue_id=9001)
    id_405 = await _add_issue(db, s.series_id, cv_issue_id=9002, issue_number="405")
    ctx = import_ctx()
    dl = tmp_path / "dl"
    # The grab record points at 405; the filename also reads 405; but the embedded
    # ComicInfo CV id resolves to 404 — a misleading disagreement.
    make_cbz_with_comicinfo(
        dl / "Batman 405 (1987).cbz", xml=comicinfo_xml(cv_issue_id=9001)
    )
    await _add_grab(
        db, download_id="dl-1", series_id=s.series_id, issue_id=id_405,
        title="Batman 405 (1987)",
    )

    outcomes = await _run(
        db, CompletedDownloadSource(download_id="dl-1", output_path=str(dl)), ctx
    )

    # Grab won silently: imported to 405, NOT the embedded 404, and NOT blocked.
    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert outcomes[0].issue_id == id_405
    async with db.read_session() as session:
        events = await history.events_for_issue(session, id_405)
    data = history.decode_data(events[0].data)
    # No conflict flag was recorded (the grab is above the embedded layer).
    assert "comicinfo_conflict" not in data["provenance"]


@pytest.mark.req("FRG-IMP-024")
async def test_tagged_file_ignores_stray_embedded_id(db, seed, import_ctx, tmp_path):
    """A file carrying our own ``[__issueid__]`` tag imports to the TAG — a stray
    embedded id below it neither overrides nor blocks (regression)."""
    s = await seed(title="Batman", issue_number="404", cv_issue_id=9001)
    id_405 = await _add_issue(db, s.series_id, cv_issue_id=9002, issue_number="405")
    ctx = import_ctx()
    dl = tmp_path / "dl"
    # The internal id tag pins IssueRow id_405; the embedded CV id resolves to 404.
    make_cbz_with_comicinfo(
        dl / f"Batman 405 (1987) [__{id_405}__].cbz",
        xml=comicinfo_xml(cv_issue_id=9001),
    )

    outcomes = await _run(
        db, CompletedDownloadSource(download_id="dl-1", output_path=str(dl)), ctx
    )

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert outcomes[0].issue_id == id_405  # the tag won, not the embedded 404
    async with db.read_session() as session:
        events = await history.events_for_issue(session, id_405)
    data = history.decode_data(events[0].data)
    assert "comicinfo_conflict" not in data["provenance"]


# --- FRG-PP-016: manual import resolution -----------------------------------


@pytest.mark.req("FRG-PP-016")
async def test_download_scoped_execute_keeps_already_imported_blocked(
    db, seed, import_ctx, tmp_path
):
    """A blocked download file the listing showed as already-imported stays blocked
    at execute when submitted with its ``downloadId`` — the download context (grab
    hints + download id) is rebuilt so ``AlreadyImportedSpec`` evaluates as it did
    in the listing, instead of the file slipping through as a bare files-only
    candidate (download_id lost) that never trips the spec (FRG-PP-016)."""
    s = await seed(title="Batman", issue_number="404", cv_issue_id=9001)
    staging = tmp_path / "staging"
    cbz = staging / "Batman 404 (1987).cbz"
    make_cbz(cbz)
    now = utcnow()
    async with db.write_session() as session:
        session.add(
            TrackedDownloadRow(
                download_id="dl-1",
                client_id=None,
                state="import_blocked",
                status="warning",
                title="Batman 404",
                output_path=str(staging),
                added_at=now,
                updated_at=now,
            )
        )
    await _add_grab(
        db, download_id="dl-1", series_id=s.series_id, issue_id=s.issue_id,
        title="Batman 404 (1987)",
    )
    # A prior successful import of THIS download for THIS issue.
    async with db.write_session() as session:
        history.record_event(
            session,
            event_type=history.EVENT_IMPORTED,
            series_id=s.series_id,
            issue_id=s.issue_id,
            download_id="dl-1",
            source_title="Batman 404",
            source=history.SOURCE_DOWNLOAD,
            now=now,
        )

    summary = await execute_manual_import(
        db, None, [ManualFileSpec(path=str(cbz), download_id="dl-1")]
    )

    assert "blocked=1" in summary
    assert "imported=0" in summary
    assert await _issue_files(db) == []  # nothing re-imported


@pytest.mark.req("FRG-PP-016")
async def test_blocked_download_resolved_by_override(db, seed, import_ctx, tmp_path):
    s = await seed(title="Batman", issue_number="404", cv_issue_id=9001)
    ctx = import_ctx()
    dl = tmp_path / "dl"
    unmatched = dl / "unknown-release-xyz.cbz"
    make_cbz(unmatched)

    source = ManualImportSource(
        download=CompletedDownloadSource(download_id="dl-1", output_path=str(dl)),
        overrides={
            str(unmatched): ManualOverride(series_id=s.series_id, issue_id=s.issue_id)
        },
    )
    outcomes = await _run(db, source, ctx)

    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    files = await _issue_files(db)
    assert len(files) == 1 and files[0].issue_id == s.issue_id
    async with db.read_session() as session:
        events = await history.events_for_issue(session, s.issue_id)
    assert events[0].event_type == "imported"
    assert events[0].source == history.SOURCE_MANUAL
    assert events[0].download_id == "dl-1"


@pytest.mark.req("FRG-PP-016")
async def test_arbitrary_folder_unmatched_files(db, seed, import_ctx, library_root):
    s = await seed(title="Batman", issue_number="404", cv_issue_id=9001)
    ctx = import_ctx()
    inbox = library_root / "inbox"
    unmatched = inbox / "unknown-release-xyz.cbz"
    make_cbz(unmatched)

    # Listing shows the would-be verdict + reasons for the unmatched file.
    listing = await list_manual_candidates(db, None, path=str(inbox))
    assert len(listing.entries) == 1
    assert listing.entries[0].approved is False
    assert any("match" in r for r in listing.entries[0].rejections)

    # A per-file override drives it to the correct issue through the pipeline.
    source = ManualImportSource(
        folder_path=str(inbox),
        overrides={
            str(unmatched): ManualOverride(series_id=s.series_id, issue_id=s.issue_id)
        },
    )
    outcomes = await _run(db, source, ctx)
    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]
    assert (await _issue_files(db))[0].issue_id == s.issue_id


@pytest.mark.req("FRG-PP-016")
async def test_override_bypasses_mapping_not_safety_specs(
    db, seed, import_ctx, library_root
):
    s = await seed(title="Batman", issue_number="404", cv_issue_id=9001)

    # (a) A corrupt archive with a perfect override still routes to FAILED.
    corrupt = make_corrupt(library_root / "corrupt.cbz")
    ctx = import_ctx()
    src = ManualImportSource(
        files=(str(corrupt),),
        overrides={
            str(corrupt): ManualOverride(series_id=s.series_id, issue_id=s.issue_id)
        },
    )
    outcomes = await _run(db, src, ctx)
    assert outcomes[0].status is ImportStatus.FAILED
    assert await _issue_files(db) == []

    # (b) A below-floor file with a perfect override still blocks as junk.
    small = library_root / "small.cbz"
    make_cbz(small)
    big_floor_ctx = import_ctx(junk_size_floor_bytes=10 * 1024 * 1024)
    src2 = ManualImportSource(
        files=(str(small),),
        overrides={
            str(small): ManualOverride(series_id=s.series_id, issue_id=s.issue_id)
        },
    )
    outcomes2 = await _run(db, src2, big_floor_ctx)
    assert outcomes2[0].status is ImportStatus.BLOCKED
    assert any("sample/junk" in r for r in outcomes2[0].reasons)
    assert await _issue_files(db) == []


@pytest.mark.req("FRG-PP-016")
async def test_override_to_nonexistent_entity_is_not_trusted(
    db, seed, import_ctx, library_root
):
    s = await seed(title="Batman", issue_number="404", cv_issue_id=9001)
    other = await seed(
        title="Superman", issue_number="1", cv_volume_id=100, cv_issue_id=8001
    )
    ctx = import_ctx()
    unmatched = library_root / "unknown-release.cbz"
    make_cbz(unmatched)

    # A phantom issue id → dropped, not fabricated.
    src = ManualImportSource(
        files=(str(unmatched),),
        overrides={str(unmatched): ManualOverride(issue_id=999999)},
    )
    outcomes = await _run(db, src, ctx)
    assert outcomes[0].status is ImportStatus.BLOCKED
    assert outcomes[0].issue_id is None
    assert await _issue_files(db) == []

    # An issue that does not belong to the named series → also dropped.
    src2 = ManualImportSource(
        files=(str(unmatched),),
        overrides={
            str(unmatched): ManualOverride(
                series_id=other.series_id, issue_id=s.issue_id
            )
        },
    )
    outcomes2 = await _run(db, src2, ctx)
    assert outcomes2[0].status is ImportStatus.BLOCKED
    assert await _issue_files(db) == []


@pytest.mark.req("FRG-PP-016")
async def test_failed_manual_candidate_stays_blocked_not_lost(
    db, seed, import_ctx, library_root, monkeypatch
):
    s = await seed(title="Batman", issue_number="404", cv_issue_id=9001)
    ctx = import_ctx()
    picked = library_root / "unknown-release.cbz"
    make_cbz(picked)

    def _boom(*args, **kwargs):
        raise OSError("disk gone")

    monkeypatch.setattr("foragerr.importer.fileops.place_file", _boom)

    src = ManualImportSource(
        files=(str(picked),),
        overrides={
            str(picked): ManualOverride(series_id=s.series_id, issue_id=s.issue_id)
        },
    )
    outcomes = await _run(db, src, ctx)

    # Parked BLOCKED (never FAILED-blocklisted for an environmental IO error),
    # the source file is untouched, and it remains available to try again.
    assert outcomes[0].status is ImportStatus.BLOCKED
    assert any("placing the file" in r for r in outcomes[0].reasons)
    assert picked.exists()
    assert await _issue_files(db) == []


# --- FRG-API-015: execution runs the full decision set (no force) -----------


@pytest.mark.req("FRG-API-015")
async def test_execute_cannot_force_a_rejected_file_past_the_specs(
    db, seed, library_root
):
    s = await seed(title="Batman", issue_number="404", cv_issue_id=9001)
    corrupt = make_corrupt(library_root / "corrupt.cbz")

    summary = await execute_manual_import(
        db,
        None,
        [
            ManualFileSpec(
                path=str(corrupt), series_id=s.series_id, issue_id=s.issue_id
            )
        ],
    )
    # The full decision set ran; the corrupt archive is reported failed, not
    # force-imported. No issue_files row was written.
    assert "failed=1" in summary
    assert await _issue_files(db) == []
