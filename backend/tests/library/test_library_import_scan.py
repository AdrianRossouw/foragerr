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
    db, tmp_path, root_folder_id, root_folder_path, caplog
):
    """The per-run proposal cap is the ``library_import_proposal_cap`` SETTING
    (not a hardcoded constant): capped-out groups stage visibly deferred."""
    cfg = tmp_path / "cfg-cap"
    cfg.mkdir()
    settings = flows_settings(cfg, library_import_proposal_cap=1)
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
async def test_second_scan_advances_previously_deferred_groups(
    db, tmp_path, root_folder_id, root_folder_path
):
    """Carry-forward keeps answered groups out of the proposal budget: a
    re-scan spends its cap on the DEFERRED group (which finally gets its
    proposal) instead of re-searching the group already answered — deferred
    groups advance rather than starving behind the same front-runners."""
    from flows_support import CV_HOST
    from http_support import PUBLIC_V4, RecordingTransport, StubResolver
    from foragerr.http import HttpClientFactory

    cfg = tmp_path / "cfg-cap"
    cfg.mkdir()
    settings = flows_settings(cfg, library_import_proposal_cap=1)
    _touch(root_folder_path / "Aardvark" / "Aardvark 001 (2000).cbz")
    _touch(root_folder_path / "Zebra" / "Zebra 001 (2000).cbz")
    cv = FakeCV().volume(1, name="Aardvark").volume(2, name="Zebra")
    factory = build_factory(settings, cv.handler())
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    first = await _groups(db, root_folder_id)
    assert first["aardvark"].proposed_cv_volume_id == 1
    assert first["zebra"].proposed_cv_volume_id is None  # deferred over cap

    # Second scan on a fresh recording transport: exactly ONE search runs
    # (zebra's) — aardvark's carried proposal is never re-searched.
    transport = RecordingTransport(cv.handler())
    factory2 = HttpClientFactory(
        settings,
        resolver=StubResolver({CV_HOST: [PUBLIC_V4]}),
        transport=transport,
    )
    await scan_library_root(db, settings, root_folder_id, factory=factory2)

    after = await _groups(db, root_folder_id)
    assert after["aardvark"].proposed_cv_volume_id == 1  # carried forward
    assert after["zebra"].proposed_cv_volume_id == 2  # finally proposed
    assert after["zebra"].state == "proposed"
    searches = [
        r for r in transport.requests if str(r.url.path).endswith("/volumes/")
    ]
    assert len(searches) == 1


@pytest.mark.req("FRG-IMP-023")
async def test_cv_outage_rescan_preserves_existing_proposals(
    db, settings, root_folder_id, root_folder_path
):
    """A ComicVine-down re-scan never wipes prior answers: carried proposals
    and display fields survive verbatim (they are not re-searched at all), and
    a NEW group hit by the outage stays retryable ``proposed`` — a degraded/
    incomplete search is not an answer."""
    import httpx

    _touch(root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz")
    cv = FakeCV().volume(101, name="Saga", start_year=2012, publisher="Image")
    factory = build_factory(settings, cv.handler())
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    before = (await _groups(db, root_folder_id))["saga"]
    assert before.proposed_cv_volume_id == 101
    assert before.proposal_name == "Saga"

    # New folder appears, then ComicVine goes down (500s degrade the search).
    _touch(root_folder_path / "Descender" / "Descender 001 (2015).cbz")
    down = build_factory(
        settings, lambda _request: httpx.Response(500, content=b"outage")
    )
    await scan_library_root(db, settings, root_folder_id, factory=down)

    after = await _groups(db, root_folder_id)
    saga = after["saga"]
    assert saga.state == "proposed"
    assert saga.proposed_cv_volume_id == 101  # preserved, not wiped
    assert saga.proposal_name == "Saga"
    assert saga.proposal_start_year == 2012
    descender = after["descender"]
    assert descender.state == "proposed"  # NOT no_match: outage != answer
    assert descender.proposed_cv_volume_id is None
    assert "incomplete" in (descender.message or "")


@pytest.mark.req("FRG-IMP-023")
async def test_staging_rows_exist_before_the_proposal_phase(
    db, settings, root_folder_id, root_folder_path, monkeypatch
):
    """Progressive staging: the replace happens BEFORE proposals, so the review
    renders within seconds of the walk and a mid-proposal restart loses only
    un-proposed matches. Asserted structurally: when the proposal phase starts,
    the rows are already persisted (proposal pending), and each group's row is
    updated as its proposal lands."""
    _touch(root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz")
    cv = FakeCV().volume(101, name="Saga")
    factory = build_factory(settings, cv.handler())

    staged_at_proposal_time: dict[str, LibraryImportGroupRow] = {}
    original = library_import._propose_matches

    async def probing(settings_, drafts, factory_, *, persist):
        staged_at_proposal_time.update(await _groups(db, root_folder_id))
        await original(settings_, drafts, factory_, persist=persist)

    monkeypatch.setattr(library_import, "_propose_matches", probing)

    await scan_library_root(db, settings, root_folder_id, factory=factory)

    row = staged_at_proposal_time["saga"]  # persisted BEFORE any proposal ran
    assert row.state == "proposed"
    assert row.proposed_cv_volume_id is None
    assert "pending" in (row.message or "")
    after = (await _groups(db, root_folder_id))["saga"]
    assert after.proposed_cv_volume_id == 101  # the proposal landed on the row
    assert after.message is None


@pytest.mark.req("FRG-IMP-023")
async def test_patch_during_the_proposal_phase_survives_the_scan(
    db, settings, root_folder_id, root_folder_path, monkeypatch
):
    """A user decision made WHILE the scan's proposal phase runs is never
    reverted: the per-group proposal update is guarded to only touch rows that
    are still undecided (state ``proposed``, no confirmed volume)."""
    _touch(root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz")
    cv = FakeCV().volume(101, name="Saga")
    factory = build_factory(settings, cv.handler())
    original = library_import._propose_matches

    async def confirm_then_propose(settings_, drafts, factory_, *, persist):
        # The user confirms (with an override) between staging and proposals.
        async with db.write_session() as session:
            rows = (
                (await session.execute(select(LibraryImportGroupRow)))
                .scalars()
                .all()
            )
            for row in rows:
                row.state = "confirmed"
                row.proposed_cv_volume_id = 999
                row.confirmed_cv_volume_id = 999
        await original(settings_, drafts, factory_, persist=persist)

    monkeypatch.setattr(library_import, "_propose_matches", confirm_then_propose)

    await scan_library_root(db, settings, root_folder_id, factory=factory)

    after = (await _groups(db, root_folder_id))["saga"]
    assert after.state == "confirmed"  # the scan's proposal did NOT clobber it
    assert after.confirmed_cv_volume_id == 999
    assert after.proposed_cv_volume_id == 999


@pytest.mark.req("FRG-IMP-023")
async def test_files_imported_mid_scan_are_dropped_at_replace_time(
    db, settings, root_folder_id, root_folder_path, format_profile_id
):
    """The tracked-file set is re-read INSIDE the replace transaction: a file
    imported after the scan snapshotted its tracked set (e.g. by a running
    execute) is never re-staged, and a group whose files all landed is dropped
    entirely rather than offered for a duplicate import."""
    imported_file = _touch(root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz")
    _touch(root_folder_path / "Descender" / "Descender 001 (2015).cbz")
    cv = FakeCV().volume(101, name="Saga").volume(303, name="Descender")
    factory = build_factory(settings, cv.handler())

    async def register_imported() -> None:
        async with db.write_session() as session:
            series = await repo.create_series(
                session,
                cv_volume_id=101,
                title="Saga",
                start_year=2012,
                format_profile_id=format_profile_id,
                root_folder_id=root_folder_id,
                path=str(root_folder_path / "Saga (2012)"),
            )
            issue = await repo.create_issue(
                session,
                series_id=series.id,
                cv_issue_id=9101,
                issue_number="1",
                cover_date=dt.date(2012, 3, 1),
            )
            await repo.add_issue_file(
                session,
                issue_id=issue.id,
                path=str(imported_file),
                size=imported_file.stat().st_size,
            )

    state = {"registered": False}

    async def offload(fn, *args):
        result = fn(*args)
        if fn.__name__ == "_walk" and not state["registered"]:
            # Simulate an import landing between the scan's tracked snapshot
            # and its staging replace (the walk runs in that window).
            state["registered"] = True
            await register_imported()
        return result

    await scan_library_root(
        db, settings, root_folder_id, offload=offload, factory=factory
    )

    groups = await _groups(db, root_folder_id)
    assert set(groups) == {"descender"}  # saga's lone file landed -> dropped


@pytest.mark.req("FRG-IMP-023")
async def test_scan_fails_fast_while_an_execute_for_the_root_is_pending(
    db, settings, root_folder_id, root_folder_path, tmp_path
):
    """A scan's delete+reinsert would invalidate the group ids a queued/running
    ``library-import`` execute holds, so the scan fails fast with a clear
    error instead — and a pending execute for a DIFFERENT root never blocks."""
    from foragerr.commands import CommandService
    from foragerr.db import utcnow
    from foragerr.library.flows.library_import import LibraryImportScanBlockedError

    async with db.write_session() as session:
        group = LibraryImportGroupRow(
            matching_key="saga",
            root_folder_id=root_folder_id,
            folder=str(root_folder_path / "Saga (2012)"),
            files=library_import.encode_group_files([("/x/Saga 001.cbz", 1)]),
            confidence=0.9,
            state="confirmed",
            confirmed_cv_volume_id=101,
            scanned_at=utcnow(),
        )
        session.add(group)
        await session.flush()
        group_id = group.id

    commands = CommandService(db, settings)  # never started: stays queued
    await commands.enqueue("library-import", {"group_ids": [group_id]})

    factory = build_factory(settings, FakeCV().handler())
    with pytest.raises(LibraryImportScanBlockedError, match="wait for it"):
        await scan_library_root(db, settings, root_folder_id, factory=factory)

    # A different root is unaffected by that pending execute.
    other = tmp_path / "other-root"
    other.mkdir()
    async with db.write_session() as session:
        other_row = await repo.create_root_folder(session, str(other))
        other_id = other_row.id
    summary = await scan_library_root(db, settings, other_id, factory=factory)
    assert "groups=0" in summary


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
