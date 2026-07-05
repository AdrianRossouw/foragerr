"""ProcessImportsCommand: completed-download drain + post-import cleanup.

FRG-DL-009 (completed download handling / blocked-not-lost / retry),
FRG-DL-010 (post-import client cleanup gating), FRG-PP-002 (state machine +
corrupt→failed branch). Grab→import runs end-to-end on scratch copies: a real
(large enough to clear the junk floor) cbz is placed under a download folder and
driven through the shared pipeline exactly as production would.
"""

from __future__ import annotations

import datetime as dt
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from foragerr.downloads.imports import _post_import_cleanup, process_imports
from foragerr.downloads.models import DownloadClientRow, TrackedDownloadRow
from foragerr.downloads.state import TrackedDownloadState
from foragerr.importer import history
from foragerr.importer.models import ImportHistoryRow
from foragerr.library.models import IssueFileRow, IssueRow
from foragerr.db import utcnow

from importer._archives import make_corrupt  # tests/importer is a package
from tracking_support import (
    FakeClient,
    insert_grab_history,
    insert_tracked,
    make_item,
    seed_library,
    tracked_by_download_id,
)

_NOW = dt.datetime(2026, 7, 5, 12, 0, 0)

# A genuine 1x1 PNG so the cbz has a real image entry (FRG-PP-006).
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f9f0000000049454e44ae42"
    "6082"
)


def make_large_cbz(path: Path, *, filler: int = 200 * 1024) -> int:
    """A valid cbz (≥1 image entry) whose on-disk size clears the 100 KiB junk
    floor via an incompressible stored filler member."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("page000.png", _PNG_1x1)
        zf.writestr("filler.bin", os.urandom(filler))
    return path.stat().st_size


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


async def _history(db, download_id: str) -> list[ImportHistoryRow]:
    async with db.read_session() as session:
        return await history.events_for_download(session, download_id)


async def _insert_client(db, *, remove_completed: bool, client_id: int = 1) -> int:
    async with db.write_session() as session:
        row = DownloadClientRow(
            name="SAB",
            implementation="sabnzbd",
            protocol="usenet",
            enabled=True,
            remove_completed_downloads=remove_completed,
            settings="{}",
            added_at=utcnow(),
        )
        session.add(row)
        await session.flush()
        return row.id


# --- FRG-DL-009 / FRG-PP-002: the happy-path drain --------------------------


@pytest.mark.req("FRG-DL-009")
@pytest.mark.req("FRG-PP-002")
async def test_process_imports_drains_pending_to_imported(db, tmp_path):
    series_id, issue_id = await seed_library(db, tmp_path)
    dl_dir = tmp_path / "downloads" / "Spawn.001.2024"
    make_large_cbz(dl_dir / "Spawn 001 (2024).cbz")
    await insert_grab_history(db, download_id="d1", series_id=series_id, issue_id=issue_id)
    await insert_tracked(
        db,
        download_id="d1",
        state=TrackedDownloadState.IMPORT_PENDING,
        client_id=None,
        series_id=series_id,
        issue_id=issue_id,
    )
    async with db.write_session() as session:
        (await tracked_by_download_id_session(session, "d1")).output_path = str(dl_dir)

    summary = await process_imports(db, None, now=_NOW)

    assert summary == "imported=1 blocked=0 failed=0"
    row = await tracked_by_download_id(db, "d1")
    assert row.state == TrackedDownloadState.IMPORTED.value
    files = await _issue_files(db, series_id)
    assert len(files) == 1 and files[0].issue_id == issue_id
    assert os.path.exists(files[0].path)  # landed in the library
    events = await _history(db, "d1")
    assert any(e.event_type == history.EVENT_IMPORTED for e in events)


# --- FRG-DL-009: blocked, never lost ----------------------------------------


@pytest.mark.req("FRG-DL-009")
async def test_unresolvable_download_blocks_and_is_not_lost(db, tmp_path):
    # No grab history + an unparseable name → cannot map to an issue.
    dl_dir = tmp_path / "downloads" / "mystery"
    src = dl_dir / "qwerty-zxcv.cbz"
    make_large_cbz(src)
    await insert_tracked(
        db,
        download_id="d-block",
        state=TrackedDownloadState.IMPORT_PENDING,
        client_id=None,
        series_id=None,
        issue_id=None,
        title="qwerty-zxcv",
    )
    async with db.write_session() as session:
        (await tracked_by_download_id_session(session, "d-block")).output_path = str(dl_dir)

    summary = await process_imports(db, None, now=_NOW)

    assert summary == "imported=0 blocked=1 failed=0"
    row = await tracked_by_download_id(db, "d-block")
    assert row.state == TrackedDownloadState.IMPORT_BLOCKED.value
    assert row.status_messages and "series and issue" in row.status_messages
    assert os.path.exists(src)  # source retained, never auto-deleted
    events = await _history(db, "d-block")
    assert any(e.event_type == history.EVENT_IMPORT_BLOCKED for e in events)


@pytest.mark.req("FRG-DL-009")
async def test_no_output_path_blocks_never_lost(db, tmp_path):
    await insert_tracked(
        db,
        download_id="d-empty",
        state=TrackedDownloadState.IMPORT_PENDING,
        client_id=None,
    )
    # insert_tracked leaves output_path NULL → nothing to import.
    summary = await process_imports(db, None, now=_NOW)
    assert summary == "imported=0 blocked=1 failed=0"
    row = await tracked_by_download_id(db, "d-empty")
    assert row.state == TrackedDownloadState.IMPORT_BLOCKED.value


# --- FRG-DL-009: retry / re-process on evidence change, without re-grab ------


@pytest.mark.req("FRG-DL-009")
async def test_blocked_item_reprocesses_to_imported_when_evidence_appears(db, tmp_path):
    series_id, issue_id = await seed_library(db, tmp_path)
    dl_dir = tmp_path / "downloads" / "later"
    make_large_cbz(dl_dir / "unparseable.cbz")
    # First pass: no grab history, unparseable → blocked.
    await insert_tracked(
        db,
        download_id="d-retry",
        state=TrackedDownloadState.IMPORT_PENDING,
        client_id=None,
        title="unparseable",
    )
    # Give it an output path (insert_tracked leaves it NULL).
    async with db.write_session() as session:
        r = await tracked_by_download_id_session(session, "d-retry")
        r.output_path = str(dl_dir)
    await process_imports(db, None, now=_NOW)
    assert (await tracked_by_download_id(db, "d-retry")).state == (
        TrackedDownloadState.IMPORT_BLOCKED.value
    )

    # Evidence appears (the grab row now resolves) and TrackDownloads re-feeds it
    # as import_pending — no fresh grab of the file itself.
    await insert_grab_history(
        db, download_id="d-retry", series_id=series_id, issue_id=issue_id
    )
    async with db.write_session() as session:
        r = await tracked_by_download_id_session(session, "d-retry")
        r.state = TrackedDownloadState.IMPORT_PENDING.value
        r.series_id, r.issue_id = series_id, issue_id

    summary = await process_imports(db, None, now=_NOW)
    assert summary == "imported=1 blocked=0 failed=0"
    assert (await tracked_by_download_id(db, "d-retry")).state == (
        TrackedDownloadState.IMPORTED.value
    )


async def tracked_by_download_id_session(session, download_id):
    return (
        await session.execute(
            select(TrackedDownloadRow).where(
                TrackedDownloadRow.download_id == download_id
            )
        )
    ).scalars().first()


# --- FRG-PP-002: the status-guarded claim never races TrackDownloads --------


@pytest.mark.req("FRG-PP-002")
async def test_claim_guard_leaves_change5_driven_states_untouched(db, tmp_path):
    # Rows TrackDownloadsCommand owns must never be claimed/regressed: only
    # import_pending (and a stale importing) are in the guard's WHERE clause.
    non_claimable = [
        ("d-dl", TrackedDownloadState.DOWNLOADING),
        ("d-fp", TrackedDownloadState.FAILED_PENDING),
        ("d-f", TrackedDownloadState.FAILED),
        ("d-blk", TrackedDownloadState.IMPORT_BLOCKED),
        ("d-ig", TrackedDownloadState.IGNORED),
    ]
    for did, state in non_claimable:
        await insert_tracked(db, download_id=did, state=state, client_id=None)

    summary = await process_imports(db, None, now=_NOW)

    assert summary == "imported=0 blocked=0 failed=0"
    for did, state in non_claimable:
        row = await tracked_by_download_id(db, did)
        assert row.state == state.value  # unchanged — guard skipped it


# --- FRG-PP-002: corrupt archive takes the failed branch --------------------


@pytest.mark.req("FRG-PP-002")
async def test_corrupt_archive_routes_to_failed_handling(db, tmp_path):
    series_id, issue_id = await seed_library(db, tmp_path)
    dl_dir = tmp_path / "downloads" / "corrupt"
    make_corrupt(dl_dir / "Spawn 001 (2024).cbz")
    await insert_grab_history(db, download_id="d-bad", series_id=series_id, issue_id=issue_id)
    await insert_tracked(
        db,
        download_id="d-bad",
        state=TrackedDownloadState.IMPORT_PENDING,
        client_id=None,
        series_id=series_id,
        issue_id=issue_id,
    )
    async with db.write_session() as session:
        r = await tracked_by_download_id_session(session, "d-bad")
        r.output_path = str(dl_dir)

    from tracking_support import FakeCommands

    commands = FakeCommands()
    summary = await process_imports(db, None, commands=commands, now=_NOW)

    assert summary == "imported=0 blocked=0 failed=1"
    row = await tracked_by_download_id(db, "d-bad")
    # process_failures promotes failed_pending → failed and blocklists + re-searches.
    assert row.state == TrackedDownloadState.FAILED.value
    events = await _history(db, "d-bad")
    assert any(e.event_type == history.EVENT_IMPORT_FAILED for e in events)
    assert any(name == "issue-search" for name, _p, _t in commands.enqueued)


# --- FRG-DL-010: post-import client cleanup gating --------------------------


@pytest.mark.req("FRG-DL-010")
@pytest.mark.parametrize("remove_completed", [True, False])
async def test_cleanup_gated_on_remove_flag(db, tmp_path, monkeypatch, remove_completed):
    client_id = await _insert_client(db, remove_completed=remove_completed)
    series_id, issue_id = await seed_library(db, tmp_path)
    dl_dir = tmp_path / "downloads" / "ok"
    make_large_cbz(dl_dir / "Spawn 001 (2024).cbz")
    await insert_grab_history(db, download_id="d-ok", series_id=series_id, issue_id=issue_id)
    await insert_tracked(
        db,
        download_id="d-ok",
        state=TrackedDownloadState.IMPORT_PENDING,
        client_id=client_id,
        series_id=series_id,
        issue_id=issue_id,
    )
    async with db.write_session() as session:
        r = await tracked_by_download_id_session(session, "d-ok")
        r.output_path = str(dl_dir)

    fake = FakeClient([make_item("d-ok", output_path=str(dl_dir))])
    import foragerr.downloads.imports as imports_mod

    async def _fake_build(db_, cid, *, settings=None):
        return fake

    monkeypatch.setattr(imports_mod, "build_client_for_id", _fake_build)

    summary = await process_imports(db, None, now=_NOW)
    assert summary == "imported=1 blocked=0 failed=0"

    if remove_completed:
        assert fake.removed == [("d-ok", True)]  # item + data deleted
        assert fake.imported == []
    else:
        assert fake.removed == []  # item + data + staging retained
        assert fake.imported == ["d-ok"]  # marked so it is not reprocessed


@pytest.mark.req("FRG-DL-010")
async def test_blocked_download_is_never_cleaned(db, tmp_path, monkeypatch):
    client_id = await _insert_client(db, remove_completed=True)
    dl_dir = tmp_path / "downloads" / "blk"
    make_large_cbz(dl_dir / "nope.cbz")
    await insert_tracked(
        db,
        download_id="d-blk",
        state=TrackedDownloadState.IMPORT_PENDING,
        client_id=client_id,
        title="nope",
    )
    async with db.write_session() as session:
        r = await tracked_by_download_id_session(session, "d-blk")
        r.output_path = str(dl_dir)

    fake = FakeClient([make_item("d-blk", output_path=str(dl_dir))])
    import foragerr.downloads.imports as imports_mod

    async def _fake_build(db_, cid, *, settings=None):
        return fake

    monkeypatch.setattr(imports_mod, "build_client_for_id", _fake_build)

    summary = await process_imports(db, None, now=_NOW)
    assert summary == "imported=0 blocked=1 failed=0"
    assert fake.removed == [] and fake.imported == []  # evidence retained for retry


# --- FRG-DL-010: cleanup helper directly (remove-vs-mark) -------------------


@pytest.mark.req("FRG-DL-010")
async def test_post_import_cleanup_marks_when_disabled(db, tmp_path, monkeypatch):
    client_id = await _insert_client(db, remove_completed=False)
    fake = FakeClient([make_item("dz", output_path="/x")])
    import foragerr.downloads.imports as imports_mod

    async def _fake_build(db_, cid, *, settings=None):
        return fake

    monkeypatch.setattr(imports_mod, "build_client_for_id", _fake_build)
    await _post_import_cleanup(db, None, client_id=client_id, download_id="dz")
    assert fake.imported == ["dz"] and fake.removed == []
