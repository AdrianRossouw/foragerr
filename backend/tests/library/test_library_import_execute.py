"""library-import execute: bulk add + shared-pipeline import (FRG-IMP-023).

Drives the staged groups end-to-end: confirm/override -> execute ->
``add_series`` (path_override in in-place mode) -> issue refresh -> the ONE
``import_candidate`` pipeline -> staging state transitions. The
``library_import_mode`` placement seam is pinned in both modes.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from flows_support import FakeCV, build_factory, flows_settings, issue
from foragerr.commands import CommandService
from foragerr.library import repo
from foragerr.library.flows import library_import
from foragerr.library.flows.library_import import (
    decode_rejections,
    execute_library_import,
    scan_library_root,
)
from foragerr.library.models import (
    IssueFileRow,
    IssueRow,
    LibraryImportGroupRow,
    SeriesRow,
)

_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f9f0000000049454e44ae42"
    "6082"
)


def make_large_cbz(path: Path, *, filler: int = 200 * 1024) -> Path:
    """A valid cbz (>=1 image entry) clearing the 100 KiB junk floor."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("page000.png", _PNG_1x1)
        zf.writestr("filler.bin", os.urandom(filler))
    return path


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return flows_settings(cfg)


async def _confirm(db, group_id: int, cv_volume_id: int) -> None:
    async with db.write_session() as session:
        group = await session.get(LibraryImportGroupRow, group_id)
        group.state = "confirmed"
        group.confirmed_cv_volume_id = cv_volume_id


async def _groups_by_key(db, root_folder_id: int) -> dict[str, LibraryImportGroupRow]:
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


async def _issue_file_paths(db, cv_volume_id: int) -> list[str]:
    async with db.read_session() as session:
        rows = (
            (
                await session.execute(
                    select(IssueFileRow.path)
                    .join(IssueRow, IssueFileRow.issue_id == IssueRow.id)
                    .join(SeriesRow, IssueRow.series_id == SeriesRow.id)
                    .where(SeriesRow.cv_volume_id == cv_volume_id)
                )
            )
            .scalars()
            .all()
        )
    return list(rows)


@pytest.mark.req("FRG-IMP-023")
async def test_mass_import_with_override_and_deselect(
    db, settings, root_folder_id, root_folder_path
):
    """Confirmed groups create their series and import through the shared
    pipeline; an overridden group uses the corrected volume even though the
    filenames parse to a different series title; a deselected group stays
    staged untouched."""
    make_large_cbz(root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz")
    # Files parse to "sagga" but the user corrects the match to Paper Girls:
    # the override must win over the disagreeing filename parse.
    overridden = make_large_cbz(
        root_folder_path / "Sagg Whatever" / "Sagga 001 (2015).cbz"
    )
    make_large_cbz(root_folder_path / "Descender" / "Descender 001 (2015).cbz")

    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .volume(202, name="Paper Girls", start_year=2015)
        .volume(303, name="Descender", start_year=2015)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
        .issues(202, [issue(9202, "1", cover_date="2015-10-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)

    await scan_library_root(db, settings, root_folder_id, factory=factory)
    groups = await _groups_by_key(db, root_folder_id)
    await _confirm(db, groups["saga"].id, 101)  # as proposed
    await _confirm(db, groups["sagga"].id, 202)  # user override

    summary = await execute_library_import(
        db,
        settings,
        [groups["saga"].id, groups["sagga"].id],
        commands=commands,
        factory=factory,
    )

    assert "imported=2" in summary
    # Both series exist; in-place mode pinned each to its scanned folder.
    async with db.read_session() as session:
        saga = (
            await session.execute(select(SeriesRow).where(SeriesRow.cv_volume_id == 101))
        ).scalars().one()
        girls = (
            await session.execute(select(SeriesRow).where(SeriesRow.cv_volume_id == 202))
        ).scalars().one()
        assert saga.path == str(root_folder_path / "Saga (2012)")
        assert girls.path == str(root_folder_path / "Sagg Whatever")
        descender_series = (
            await session.execute(select(SeriesRow).where(SeriesRow.cv_volume_id == 303))
        ).scalars().first()
    assert descender_series is None  # deselected group added nothing

    assert len(await _issue_file_paths(db, 101)) == 1
    girls_files = await _issue_file_paths(db, 202)
    assert len(girls_files) == 1
    assert girls_files[0].startswith(str(overridden.parent))  # stayed in its folder

    after = await _groups_by_key(db, root_folder_id)
    assert after["saga"].state == "imported"
    assert after["sagga"].state == "imported"
    assert after["descender"].state == "proposed"  # stays staged, untouched


@pytest.mark.req("FRG-IMP-023")
async def test_in_place_registers_files_without_moving_them(
    db, tmp_path, root_folder_id, root_folder_path
):
    """in_place (default) + rename disabled: the file is registered at its
    existing path — same inode, same mtime, no move/copy/rename."""
    cfg = tmp_path / "cfg-noren"
    cfg.mkdir()
    settings = flows_settings(cfg, rename_enabled=False)
    original = make_large_cbz(root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz")
    stat_before = original.stat()

    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    groups = await _groups_by_key(db, root_folder_id)
    await _confirm(db, groups["saga"].id, 101)

    summary = await execute_library_import(
        db, settings, [groups["saga"].id], commands=commands, factory=factory
    )

    assert "imported=1" in summary
    paths = await _issue_file_paths(db, 101)
    assert paths == [str(original)]  # registered AT the existing path
    stat_after = original.stat()
    assert stat_after.st_ino == stat_before.st_ino  # same inode: never moved
    assert stat_after.st_mtime_ns == stat_before.st_mtime_ns  # never rewritten
    after = await _groups_by_key(db, root_folder_id)
    assert after["saga"].state == "imported"
    assert "imported=1" in (after["saga"].message or "")


@pytest.mark.req("FRG-PP-020")
async def test_fresh_settings_in_place_import_renames_nothing(
    db, tmp_path, root_folder_id, root_folder_path
):
    """A fresh-settings instance (no persisted config, no overrides) SHALL NOT
    modify adopted files: rename_enabled now defaults to off (naming-defaults),
    so an in_place library import registers every file at its exact original
    path and name — byte-identical before and after, and untouched even though
    it doesn't match the naming template's canonical output."""
    cfg = tmp_path / "cfg-freshdefaults"
    cfg.mkdir()
    settings = flows_settings(cfg)  # no rename_enabled override: real default
    assert settings.rename_enabled is False  # sanity: exercising the shipped default

    # Deliberately NOT template-shaped, so a mistaken rename would be visible.
    original = make_large_cbz(
        root_folder_path / "Saga (2012)" / "saga_001_scanlated (2012).cbz"
    )
    path_before = str(original)
    stat_before = original.stat()

    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    groups = await _groups_by_key(db, root_folder_id)
    await _confirm(db, groups["saga"].id, 101)

    summary = await execute_library_import(
        db, settings, [groups["saga"].id], commands=commands, factory=factory
    )

    assert "imported=1" in summary
    paths = await _issue_file_paths(db, 101)
    assert paths == [path_before]  # byte-identical original path+name
    stat_after = original.stat()
    assert stat_after.st_ino == stat_before.st_ino  # same inode: never moved
    assert stat_after.st_mtime_ns == stat_before.st_mtime_ns  # never rewritten


@pytest.mark.req("FRG-IMP-023")
async def test_move_mode_routes_through_normal_placement(
    db, tmp_path, root_folder_id, root_folder_path
):
    """library_import_mode=move: the series gets the normal root-relative
    folder and the file moves/renames through place_file like a download."""
    cfg = tmp_path / "cfg-move"
    cfg.mkdir()
    settings = flows_settings(cfg, library_import_mode="move")
    original = make_large_cbz(root_folder_path / "saga-dump" / "Saga 001 (2012).cbz")

    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    groups = await _groups_by_key(db, root_folder_id)
    await _confirm(db, groups["saga"].id, 101)

    summary = await execute_library_import(
        db, settings, [groups["saga"].id], commands=commands, factory=factory
    )

    assert "imported=1" in summary
    async with db.read_session() as session:
        series = (
            await session.execute(select(SeriesRow).where(SeriesRow.cv_volume_id == 101))
        ).scalars().one()
    # Normal build_series_path under the batch root, not the scanned folder.
    assert series.path == str(root_folder_path / "Saga (2012)")
    paths = await _issue_file_paths(db, 101)
    assert len(paths) == 1
    placed = Path(paths[0])
    assert placed.parent == root_folder_path / "Saga (2012)"
    assert placed.exists()
    assert not original.exists()  # moved out of the scanned folder


@pytest.mark.req("FRG-IMP-023")
async def test_blocked_files_leave_group_reviewable_with_visible_reasons(
    db, settings, root_folder_id, root_folder_path
):
    """A group whose file fails the safety specs stays confirmed with the
    blocked reasons visible on the staging row — never silently dropped."""
    corrupt = root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"not a zip at all" * 20_000)  # big enough, invalid

    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    groups = await _groups_by_key(db, root_folder_id)
    await _confirm(db, groups["saga"].id, 101)

    summary = await execute_library_import(
        db, settings, [groups["saga"].id], commands=commands, factory=factory
    )

    assert summary == "blocked=1"
    after = await _groups_by_key(db, root_folder_id)
    group = after["saga"]
    assert group.state == "confirmed"  # re-runnable after the user fixes it
    assert "blocked=1" in (group.message or "")
    assert "Saga 001 (2012).cbz" in (group.message or "")
    # The per-file reasons also round-trip STRUCTURED (not only flattened into
    # the summary): one entry per blocked file, naming file and reason.
    rejections = decode_rejections(group.rejections)
    assert len(rejections) == 1
    assert rejections[0].startswith("Saga 001 (2012).cbz: ")
    assert await _issue_file_paths(db, 101) == []


@pytest.mark.req("FRG-NFR-016")
async def test_failed_group_logs_a_warning_with_group_and_reason(
    db, settings, root_folder_id, root_folder_path, caplog
):
    """A blocked group emits one WARNING naming the group and its verbatim
    recorded reason (F11: five failures were hidden behind an INFO totals line;
    the per-group reasons existed only as UI card state)."""
    import logging

    corrupt = root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"not a zip at all" * 20_000)  # big enough, invalid

    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    groups = await _groups_by_key(db, root_folder_id)
    await _confirm(db, groups["saga"].id, 101)

    with caplog.at_level(
        logging.WARNING, logger="foragerr.library.flows.library_import"
    ):
        summary = await execute_library_import(
            db, settings, [groups["saga"].id], commands=commands, factory=factory
        )

    assert summary == "blocked=1"
    warnings = [
        r
        for r in caplog.records
        if r.name == "foragerr.library.flows.library_import"
        and r.levelno == logging.WARNING
        and "group" in r.getMessage()
    ]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "saga" in message  # the group identity (matching_key)
    assert "Saga 001 (2012).cbz" in message  # its verbatim recorded reason


@pytest.mark.req("FRG-IMP-023")
async def test_execute_auto_confirms_proposed_groups_with_a_proposal(
    db, settings, root_folder_id, root_folder_path
):
    """Selection IS confirmation: executing a ``proposed`` group that carries a
    proposal promotes it (confirmed volume = the proposal) and imports it —
    no explicit PATCH confirm required for the happy path."""
    make_large_cbz(root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz")
    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    group = (await _groups_by_key(db, root_folder_id))["saga"]
    assert group.state == "proposed"
    assert group.proposed_cv_volume_id == 101
    assert group.confirmed_cv_volume_id is None

    summary = await execute_library_import(
        db, settings, [group.id], commands=commands, factory=factory
    )

    assert "imported=1" in summary
    after = (await _groups_by_key(db, root_folder_id))["saga"]
    assert after.state == "imported"
    assert after.confirmed_cv_volume_id == 101  # the proposal was adopted
    assert len(await _issue_file_paths(db, 101)) == 1


@pytest.mark.req("FRG-IMP-023")
async def test_execute_still_skips_groups_without_any_usable_volume(
    db, settings, root_folder_id, root_folder_path
):
    """Auto-confirm never guesses: a proposal-less ``proposed`` group and a
    ``no_match`` group are counted not-confirmed and left untouched."""
    from foragerr.db import utcnow

    async with db.write_session() as session:
        rows = [
            LibraryImportGroupRow(
                matching_key=key,
                root_folder_id=root_folder_id,
                folder=str(root_folder_path / key),
                files=library_import.encode_group_files([(f"/x/{key}.cbz", 1)]),
                confidence=0.5,
                state=state,
                scanned_at=utcnow(),
            )
            for key, state in (("deferred", "proposed"), ("mystery", "no_match"))
        ]
        session.add_all(rows)
        await session.flush()
        ids = [row.id for row in rows]
    factory = build_factory(settings, FakeCV().handler())
    commands = CommandService(db, settings)

    summary = await execute_library_import(
        db, settings, ids, commands=commands, factory=factory
    )

    assert summary == "not-confirmed=2"
    after = await _groups_by_key(db, root_folder_id)
    assert after["deferred"].state == "proposed"
    assert after["mystery"].state == "no_match"


@pytest.mark.req("FRG-IMP-023")
async def test_exactly_one_metadata_refresh_per_imported_group(
    db, settings, root_folder_id, root_folder_path
):
    """The flow's direct awaited refresh is the ONLY one: ``add_series`` is
    called with ``enqueue_refresh=False``, so no queued ``refresh-series``
    doubles the ComicVine fetches/scan or reconciles mid-import."""
    from flows_support import CV_HOST
    from http_support import PUBLIC_V4, RecordingTransport, StubResolver
    from foragerr.db import CommandRow
    from foragerr.http import HttpClientFactory

    make_large_cbz(root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz")
    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
    )
    transport = RecordingTransport(cv.handler())
    factory = HttpClientFactory(
        settings,
        resolver=StubResolver({CV_HOST: [PUBLIC_V4]}),
        transport=transport,
    )
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    group = (await _groups_by_key(db, root_folder_id))["saga"]
    await _confirm(db, group.id, 101)
    issues_before = sum(
        1 for r in transport.requests if str(r.url.path).endswith("/issues/")
    )

    summary = await execute_library_import(
        db, settings, [group.id], commands=commands, factory=factory
    )

    assert "imported=1" in summary
    issue_fetches = (
        sum(1 for r in transport.requests if str(r.url.path).endswith("/issues/"))
        - issues_before
    )
    assert issue_fetches == 1  # ONE refresh fetched the volume's issues once
    async with db.read_session() as session:
        queued_refreshes = (
            (
                await session.execute(
                    select(CommandRow).where(CommandRow.name == "refresh-series")
                )
            )
            .scalars()
            .all()
        )
    assert queued_refreshes == []  # nothing enqueued to run it a second time


@pytest.mark.req("FRG-IMP-023")
async def test_existing_series_elsewhere_blocks_the_group_without_moving_files(
    db, settings, root_folder_id, root_folder_path, format_profile_id
):
    """The volume already has a series at a DIFFERENT folder: the group blocks
    with a visible message and its files are left untouched — never
    place_file-moved across roots at the foreign series."""
    elsewhere = root_folder_path / "Saga Elsewhere"
    elsewhere.mkdir(parents=True)
    async with db.write_session() as session:
        await repo.create_series(
            session,
            cv_volume_id=101,
            title="Saga",
            start_year=2012,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=str(elsewhere),
        )
    staged = make_large_cbz(root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz")
    cv = FakeCV().volume(101, name="Saga", start_year=2012)
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    group = (await _groups_by_key(db, root_folder_id))["saga"]
    await _confirm(db, group.id, 101)

    summary = await execute_library_import(
        db, settings, [group.id], commands=commands, factory=factory
    )

    assert summary == "duplicate=1"
    after = (await _groups_by_key(db, root_folder_id))["saga"]
    assert after.state == "confirmed"  # visible, resolvable — not silently lost
    assert "volume already in library at" in (after.message or "")
    assert str(elsewhere) in (after.message or "")
    assert "files left untouched" in (after.message or "")
    assert staged.exists()  # never moved
    assert await _issue_file_paths(db, 101) == []  # never registered either


@pytest.mark.req("FRG-IMP-023")
async def test_reused_issueless_series_is_refreshed_before_import(
    db, settings, root_folder_id, root_folder_path, format_profile_id
):
    """In-place re-run against an EXISTING series row for the same folder whose
    issue list is still empty (its add-time refresh never ran): the flow
    refreshes first so the files have issues to match, then imports."""
    folder = root_folder_path / "Saga (2012)"
    make_large_cbz(folder / "Saga 001 (2012).cbz")
    async with db.write_session() as session:
        await repo.create_series(
            session,
            cv_volume_id=101,
            title="Saga",
            start_year=2012,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=str(folder),  # SAME folder as the group -> safe reuse branch
        )
    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    group = (await _groups_by_key(db, root_folder_id))["saga"]
    await _confirm(db, group.id, 101)

    summary = await execute_library_import(
        db, settings, [group.id], commands=commands, factory=factory
    )

    assert "imported=1" in summary  # would be blocked without the refresh
    assert len(await _issue_file_paths(db, 101)) == 1


@pytest.mark.req("FRG-IMP-023")
async def test_group_at_the_root_folder_itself_blocks_in_place(
    db, settings, root_folder_id, root_folder_path
):
    """A group whose folder resolves to the ROOT itself (loose files at the
    root) must never become a series with path == root — a later per-series
    rescan would swallow the whole library. In in-place mode it blocks with a
    visible message."""
    loose = make_large_cbz(root_folder_path / "Saga 001 (2012).cbz")
    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    group = (await _groups_by_key(db, root_folder_id))["saga"]
    assert group.folder == str(root_folder_path)
    await _confirm(db, group.id, 101)

    summary = await execute_library_import(
        db, settings, [group.id], commands=commands, factory=factory
    )

    assert summary == "no-folder=1"
    after = (await _groups_by_key(db, root_folder_id))["saga"]
    assert after.state == "confirmed"
    assert "no dedicated folder" in (after.message or "")
    assert loose.exists()
    async with db.read_session() as session:
        series = (
            (await session.execute(select(SeriesRow))).scalars().all()
        )
    assert series == []  # no root-swallowing series row was created


@pytest.mark.req("FRG-IMP-023")
async def test_group_spanning_sibling_folders_blocks_in_place(
    db, settings, root_folder_id, root_folder_path
):
    """Two sibling folders whose files fold to ONE matching key make the
    group's common folder the root itself — same guard, same visible block."""
    make_large_cbz(root_folder_path / "Saga v1" / "Saga 001 (2012).cbz")
    make_large_cbz(root_folder_path / "Saga v2" / "Saga 002 (2012).cbz")
    cv = FakeCV().volume(101, name="Saga", start_year=2012)
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    group = (await _groups_by_key(db, root_folder_id))["saga"]
    assert group.folder == str(root_folder_path)  # commonpath of siblings
    await _confirm(db, group.id, 101)

    summary = await execute_library_import(
        db, settings, [group.id], commands=commands, factory=factory
    )

    assert summary == "no-folder=1"
    after = (await _groups_by_key(db, root_folder_id))["saga"]
    assert "no dedicated folder" in (after.message or "")


@pytest.mark.req("FRG-IMP-023")
async def test_group_at_the_root_imports_normally_in_move_mode(
    db, tmp_path, root_folder_id, root_folder_path
):
    """The root-folder guard is in-place-only: in move mode the loose-files
    group builds a NORMAL per-series path under the root and imports."""
    cfg = tmp_path / "cfg-move-root"
    cfg.mkdir()
    settings = flows_settings(cfg, library_import_mode="move")
    original = make_large_cbz(root_folder_path / "Saga 001 (2012).cbz")
    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    group = (await _groups_by_key(db, root_folder_id))["saga"]
    await _confirm(db, group.id, 101)

    summary = await execute_library_import(
        db, settings, [group.id], commands=commands, factory=factory
    )

    assert "imported=1" in summary
    async with db.read_session() as session:
        series = (
            await session.execute(select(SeriesRow).where(SeriesRow.cv_volume_id == 101))
        ).scalars().one()
    assert series.path == str(root_folder_path / "Saga (2012)")  # NOT the root
    paths = await _issue_file_paths(db, 101)
    assert len(paths) == 1
    assert Path(paths[0]).parent == root_folder_path / "Saga (2012)"
    assert not original.exists()  # moved into the dedicated folder


@pytest.mark.req("FRG-NFR-016")
async def test_add_failed_group_also_logs_a_warning(
    db, settings, root_folder_id, root_folder_path, caplog
):
    """The other named outcome: two flat-folder groups confirmed to distinct
    volumes collide on the shared series path — the second add-fails, and that
    group too must emit its WARNING with the verbatim reason (gate finding:
    only `blocked` was covered)."""
    import logging

    flat = root_folder_path / "flat"
    flat.mkdir(parents=True)
    make_large_cbz(flat / "saga_vol1.cbz")
    make_large_cbz(flat / "fables_vol1.cbz")

    cv = (
        FakeCV()
        .volume(101, name="Saga", start_year=2012)
        .issues(101, [issue(9101, "1", cover_date="2012-03-01")])
        .volume(202, name="Fables", start_year=2002)
        .issues(202, [issue(9202, "1", cover_date="2002-07-01")])
    )
    factory = build_factory(settings, cv.handler())
    commands = CommandService(db, settings)
    await scan_library_root(db, settings, root_folder_id, factory=factory)
    groups = await _groups_by_key(db, root_folder_id)
    await _confirm(db, groups["saga"].id, 101)
    await _confirm(db, groups["fables"].id, 202)

    with caplog.at_level(
        logging.WARNING, logger="foragerr.library.flows.library_import"
    ):
        await execute_library_import(
            db,
            settings,
            [groups["saga"].id, groups["fables"].id],
            commands=commands,
            factory=factory,
        )

    warned = [
        r.getMessage()
        for r in caplog.records
        if r.name == "foragerr.library.flows.library_import"
        and r.levelno == logging.WARNING
        and "add failed:" in r.getMessage()
    ]
    assert len(warned) == 1
    assert "'fables'" in warned[0]  # the group identity
    assert "already used by another series" in warned[0]  # verbatim reason
