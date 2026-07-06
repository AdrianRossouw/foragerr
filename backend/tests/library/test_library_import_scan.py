"""library-import-scan: staging groups, reconciliation, proposals (FRG-IMP-022/023).

Drives :func:`foragerr.library.flows.library_import.scan_library_root` directly
with a FakeCV-backed factory (real ComicVine client, no network). Command
transport correctness is covered by the API tests.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import select

from flows_support import FakeCV, build_factory, flows_settings
from foragerr.library import repo
from foragerr.library.flows import library_import
from foragerr.library.flows.library_import import scan_library_root
from foragerr.library.models import IssueFileRow, LibraryImportGroupRow


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return flows_settings(cfg)


def _touch(path: Path, content: bytes = b"comicbytes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


async def _groups(db, root_folder_id: int) -> dict[str, LibraryImportGroupRow]:
    async with db.read_session() as session:
        rows = (
            (
                await session.execute(
                    select(LibraryImportGroupRow).where(
                        LibraryImportGroupRow.root_folder_id == root_folder_id
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return {row.matching_key: row for row in rows}


@pytest.mark.req("FRG-IMP-023")
async def test_scan_stages_groups_keyed_by_matching_key_and_persisted(
    db, settings, root_folder_id, root_folder_path
):
    saga1 = _touch(root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz")
    saga2 = _touch(root_folder_path / "Saga (2012)" / "Saga 002 (2012).cbz")
    girls = _touch(root_folder_path / "Paper Girls" / "Paper Girls 001 (2015).cbz")
    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .volume(202, name="Paper Girls", start_year=2015)
    )
    factory = build_factory(settings, cv.handler())

    summary = await scan_library_root(
        db, settings, root_folder_id, factory=factory
    )

    assert "groups=2" in summary
    groups = await _groups(db, root_folder_id)
    assert set(groups) == {"saga", "paper girls"}

    saga = groups["saga"]
    assert saga.state == "proposed"
    assert saga.proposed_cv_volume_id == 101
    assert saga.folder == str(root_folder_path / "Saga (2012)")
    staged = dict(library_import.decode_group_files(saga.files))
    assert set(staged) == {str(saga1), str(saga2)}
    assert saga.confidence > 0.0
    assert saga.scanned_at is not None  # persisted staging — survives a restart

    assert groups["paper girls"].proposed_cv_volume_id == 202
    assert dict(library_import.decode_group_files(groups["paper girls"].files)) == {
        str(girls): girls.stat().st_size
    }


@pytest.mark.req("FRG-IMP-022")
async def test_scan_reconciles_vanished_rows_at_root_scope(
    db, settings, root_folder_id, root_folder_path, format_profile_id
):
    """A deleted file's issue_files row is removed BEFORE staging, so a stale
    record never blocks re-import of a replacement file."""
    series_dir = root_folder_path / "Spawn (2024)"
    series_dir.mkdir(parents=True)
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=7,
            title="Spawn",
            start_year=2024,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=str(series_dir),
        )
        issue = await repo.create_issue(
            session,
            series_id=series.id,
            cv_issue_id=70,
            issue_number="1",
            cover_date=dt.date(2024, 1, 1),
        )
        await repo.add_issue_file(
            session,
            issue_id=issue.id,
            path=str(series_dir / "Spawn 001 (2024).cbz"),  # never on disk
            size=123,
        )
    factory = build_factory(settings, FakeCV().handler())

    summary = await scan_library_root(db, settings, root_folder_id, factory=factory)

    assert "vanished_removed=1" in summary
    async with db.read_session() as session:
        remaining = (
            (await session.execute(select(IssueFileRow.id))).scalars().all()
        )
    assert remaining == []


@pytest.mark.req("FRG-IMP-023")
async def test_unparseable_and_no_match_groups_stay_staged_never_dropped(
    db, settings, root_folder_id, root_folder_path
):
    # Neither the filename nor the folder yields a series key -> unparseable.
    _touch(root_folder_path / "!!!" / "!!!.cbz")
    _touch(root_folder_path / "Obscuriton" / "Obscuriton 001 (2001).cbz")
    factory = build_factory(settings, FakeCV().handler())  # CV knows nothing

    await scan_library_root(db, settings, root_folder_id, factory=factory)

    groups = await _groups(db, root_folder_id)
    assert len(groups) == 2
    unparsed = groups["!!!"]  # folder-name fallback key keeps it reviewable
    assert unparsed.state == "no_match"
    assert unparsed.proposed_cv_volume_id is None
    assert "could not be parsed" in (unparsed.message or "")
    assert unparsed.confidence == 0.0

    unmatched = groups["obscuriton"]
    assert unmatched.state == "no_match"
    assert unmatched.proposed_cv_volume_id is None
    assert "no comicvine results" in (unmatched.message or "")


@pytest.mark.req("FRG-IMP-023")
async def test_rescan_replaces_staging_and_carries_user_decisions(
    db, settings, root_folder_id, root_folder_path
):
    _touch(root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz")
    _touch(root_folder_path / "Descender" / "Descender 001 (2015).cbz")
    cv = FakeCV().volume(101, name="Saga").volume(303, name="Descender")
    factory = build_factory(settings, cv.handler())
    await scan_library_root(db, settings, root_folder_id, factory=factory)

    groups = await _groups(db, root_folder_id)
    async with db.write_session() as session:
        saga = await session.get(LibraryImportGroupRow, groups["saga"].id)
        saga.state = "confirmed"
        saga.confirmed_cv_volume_id = 101
        desc = await session.get(LibraryImportGroupRow, groups["descender"].id)
        desc.state = "skipped"

    # A new folder appears; the re-scan replaces the root's rows atomically but
    # carries the confirm/skip decisions for groups whose key persists.
    _touch(root_folder_path / "Paper Girls" / "Paper Girls 001 (2015).cbz")
    cv.volume(202, name="Paper Girls")
    await scan_library_root(db, settings, root_folder_id, factory=factory)

    after = await _groups(db, root_folder_id)
    assert set(after) == {"saga", "descender", "paper girls"}
    assert after["saga"].state == "confirmed"
    assert after["saga"].confirmed_cv_volume_id == 101
    assert after["descender"].state == "skipped"
    assert after["paper girls"].state == "proposed"
    assert after["saga"].id != groups["saga"].id  # replaced, not updated


@pytest.mark.req("FRG-IMP-023")
async def test_proposal_cap_defers_extra_groups_visibly(
    db, settings, root_folder_id, root_folder_path, monkeypatch, caplog
):
    monkeypatch.setattr(library_import, "LIBRARY_IMPORT_PROPOSAL_CAP", 1)
    # Two one-file groups: the larger-first ordering is a tie, so the key
    # ordering makes "aardvark" the proposed one deterministically.
    _touch(root_folder_path / "Aardvark" / "Aardvark 001 (2000).cbz")
    _touch(root_folder_path / "Zebra" / "Zebra 001 (2000).cbz")
    cv = FakeCV().volume(1, name="Aardvark").volume(2, name="Zebra")
    factory = build_factory(settings, cv.handler())

    with caplog.at_level("WARNING"):
        await scan_library_root(db, settings, root_folder_id, factory=factory)

    groups = await _groups(db, root_folder_id)
    assert groups["aardvark"].proposed_cv_volume_id == 1
    deferred = groups["zebra"]
    assert deferred.state == "proposed"
    assert deferred.proposed_cv_volume_id is None
    assert "match proposal deferred" in (deferred.message or "")
    assert any("beyond the 1-proposal cap" in r.message for r in caplog.records)


@pytest.mark.req("FRG-IMP-023")
async def test_already_imported_files_never_restage(
    db, settings, root_folder_id, root_folder_path, format_profile_id
):
    """Re-check semantics: a file registered in issue_files is invisible to the
    scan, so a re-scan after import never duplicates it."""
    series_dir = root_folder_path / "Saga (2012)"
    on_disk = _touch(series_dir / "Saga 001 (2012).cbz")
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=101,
            title="Saga",
            start_year=2012,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=str(series_dir),
        )
        issue = await repo.create_issue(
            session,
            series_id=series.id,
            cv_issue_id=9101,
            issue_number="1",
            cover_date=dt.date(2012, 3, 1),
        )
        await repo.add_issue_file(
            session, issue_id=issue.id, path=str(on_disk), size=on_disk.stat().st_size
        )
    factory = build_factory(settings, FakeCV().volume(101, name="Saga").handler())

    summary = await scan_library_root(db, settings, root_folder_id, factory=factory)

    assert "groups=0" in summary
    assert await _groups(db, root_folder_id) == {}
