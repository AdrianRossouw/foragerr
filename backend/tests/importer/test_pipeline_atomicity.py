"""FS↔DB atomicity + isolation + deterministic reconciliation regressions.

Covers the merge-gate findings on the shared pipeline:

- FRG-PP-010 — an upgrade places the new file BEFORE quarantining/​swapping, so a
  ``place_file`` failure never strands the superseded file at a vanished path.
- FRG-PP-002 / FRG-DL-009 — a per-candidate ``place_file`` failure is isolated
  (SAVEPOINT) and turned into a BLOCKED outcome, so it cannot roll back an
  already-moved sibling's committed ``issue_files`` row.
- FRG-PP-004 — a re-grabbed download id reconciles to the LATEST grab row.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from fractions import Fraction

from foragerr.downloads.models import GrabHistoryRow
from foragerr.importer.pipeline import ImportStatus, gather, import_candidate
from foragerr.importer.sources import CompletedDownloadSource, RescanSource
from foragerr.library import matching, repo
from foragerr.library.models import IssueFileRow
from foragerr.parser.result import Issue

from importer._archives import make_cbz


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


async def _run(db, source, ctx):
    outcomes = []
    async with db.write_session() as session:
        for candidate in await gather(source, session, ctx):
            outcomes.append(await import_candidate(session, candidate, ctx))
    return outcomes


# --- FRG-PP-010: place-first ordering survives a placement failure ----------


@pytest.mark.req("FRG-PP-010")
async def test_upgrade_place_failure_leaves_old_file_and_row_intact(
    db, seed, import_ctx, tmp_path, monkeypatch
):
    s = await seed()
    ctx = import_ctx()
    old = s.series_path / "Batman 404 old.cbr"
    old.write_bytes(b"old-cbr-file-contents-longer-than-floor" * 4)
    async with db.write_session() as session:
        await repo.add_issue_file(
            session, issue_id=s.issue_id, path=str(old), size=old.stat().st_size
        )

    dl_dir = tmp_path / "download" / "up"
    make_cbz(dl_dir / "Batman 404 (1987).cbz")  # cbz outranks cbr → an upgrade
    await _add_grab(
        db, download_id="dl-up", series_id=s.series_id, issue_id=s.issue_id,
        title="Batman 404 (1987)",
    )

    # The placement of the new file fails (disk error) mid-import.
    import foragerr.importer.fileops as fileops_mod

    def _boom(*a, **k):
        raise OSError("disk exploded placing the new file")

    monkeypatch.setattr(fileops_mod, "place_file", _boom)

    source = CompletedDownloadSource(download_id="dl-up", output_path=str(dl_dir))
    outcomes = await _run(db, source, ctx)

    # Blocked, never lost — and, crucially, the old file was NOT quarantined
    # first: it is still on disk and its issue_files row still points at it.
    assert outcomes[0].status is ImportStatus.BLOCKED
    assert old.exists()  # never moved to quarantine before the failed placement
    async with db.read_session() as session:
        files = (await session.execute(select(IssueFileRow))).scalars().all()
    assert len(files) == 1 and files[0].path == str(old)


# --- FRG-PP-002 / FRG-DL-009: one candidate's failure can't roll back a sibling


@pytest.mark.req("FRG-PP-002")
@pytest.mark.req("FRG-DL-009")
async def test_candidate_io_failure_does_not_roll_back_moved_sibling(
    db, seed, import_ctx, tmp_path, monkeypatch
):
    s1 = await seed(title="Batman", issue_number="404", cv_volume_id=42, cv_issue_id=9001)
    s2 = await seed(
        title="Spawn", start_year=2024, issue_number="1", cv_volume_id=77, cv_issue_id=9002
    )
    ctx = import_ctx()
    dl_dir = tmp_path / "download" / "batch"
    make_cbz(dl_dir / f"good [__{s1.issue_id}__].cbz")
    make_cbz(dl_dir / f"boom [__{s2.issue_id}__].cbz")

    import foragerr.importer.fileops as fileops_mod

    real_place = fileops_mod.place_file

    def _selective(src, dst, **k):
        if "boom" in str(src):
            raise OSError("disk error placing this sibling")
        return real_place(src, dst, **k)

    monkeypatch.setattr(fileops_mod, "place_file", _selective)

    source = CompletedDownloadSource(download_id="dl-batch", output_path=str(dl_dir))
    outcomes = await _run(db, source, ctx)

    # One imported, one blocked — and the failure did not escape/​roll the batch.
    assert sorted(o.status.value for o in outcomes) == ["blocked", "imported"]
    async with db.read_session() as session:
        files = (await session.execute(select(IssueFileRow))).scalars().all()
    # The good sibling's row committed despite the other candidate failing.
    assert len(files) == 1 and files[0].issue_id == s1.issue_id
    assert os.path.exists(files[0].path)


# --- FRG-PP-004: deterministic latest-grab reconciliation -------------------


@pytest.mark.req("FRG-PP-004")
async def test_latest_grab_wins_on_redownload(db, seed, import_ctx, tmp_path):
    s1 = await seed(title="Batman", issue_number="404", cv_volume_id=42, cv_issue_id=9001)
    s2 = await seed(
        title="Spawn", start_year=2024, issue_number="1", cv_volume_id=77, cv_issue_id=9002
    )
    ctx = import_ctx()
    dl_dir = tmp_path / "download" / "re"
    make_cbz(dl_dir / "zzz-unparseable-name.cbz")  # no series/issue in the name

    # Two grab rows for the SAME download id (a re-grab): an earlier stale one and
    # then the current one. Reconciliation must take the LATEST deterministically.
    await _add_grab(
        db, download_id="d-re", series_id=s1.series_id, issue_id=s1.issue_id, title="stale grab"
    )
    await _add_grab(
        db, download_id="d-re", series_id=s2.series_id, issue_id=s2.issue_id, title="current grab"
    )

    source = CompletedDownloadSource(download_id="d-re", output_path=str(dl_dir))
    outcomes = await _run(db, source, ctx)

    assert outcomes[0].status is ImportStatus.IMPORTED
    assert outcomes[0].issue_id == s2.issue_id  # the latest grab, not an arbitrary row


# --- FRG-PP-003: matching agrees with the scanner (casefold issue names) -----


@pytest.mark.req("FRG-PP-003")
def test_issue_equal_is_case_insensitive_like_the_scanner():
    # The shared matcher casefolds issue names, so a file whose issue-name casing
    # differs from the stored issue still matches — the importer must agree with
    # the scanner (which already casefolds) or it silently misses these.
    stored = Issue(value=Fraction(1), display="1", name="Director's Cut")
    parsed = Issue(value=Fraction(1), display="1", name="director's CUT")
    assert matching.issue_equal(stored, parsed)
    # A genuinely different name still does not match.
    assert not matching.issue_equal(stored, Issue(value=Fraction(1), display="1", name="Annual"))


# --- FRG-PP-006 / FRG-PP-007: FS-heavy work routes through ctx.offload -------


@pytest.mark.req("FRG-PP-006")
@pytest.mark.req("FRG-PP-007")
async def test_place_and_inspect_run_through_the_offload_seam(db, seed, import_ctx):
    s = await seed()
    calls: list[str] = []

    async def _recording_offload(func, *args, **kwargs):
        calls.append(getattr(func, "__name__", repr(func)))
        return func(*args, **kwargs)

    ctx = import_ctx(offload=_recording_offload)
    make_cbz(s.series_path / "Batman 404 (1987).cbz")  # rescan drop-in

    outcomes = await _run(db, RescanSource(series_id=s.series_id), ctx)

    assert outcomes[0].status is ImportStatus.IMPORTED
    # Both the multi-GB copy and the archive inspection ran off the event loop.
    assert "place_file" in calls
    assert "inspect_archive" in calls
