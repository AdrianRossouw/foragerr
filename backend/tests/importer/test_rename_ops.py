"""Rename preview + execute for existing library files (FRG-PP-012).

Covers every delta-spec scenario: a pure disk-free preview, execute applying
exactly the previewed changed moves, one rename event per renamed file in the
caller's transaction, no-op entries marked unchanged and excluded, and the
round-trip contract holding for every previewed name.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from foragerr.importer import history
from foragerr.importer.rename_ops import (
    execute_renames,
    load_rename_inputs,
    preview_renames,
)
from foragerr.library import repo
from foragerr.library.models import IssueFileRow
from foragerr.parser import parse
from foragerr.parser.normalize import matching_key
from foragerr.parser.ordering import sort_key
from foragerr.parser.result import Issue
from foragerr.library.ordering import encode_sort_key


def _correct_name(issue_number: int) -> str:
    """The default-template rendering for a Batman (1987) issue (FRG-PP-020: the
    shipped default is tag-free, so no internal-row-id segment appears)."""
    return f"Batman {issue_number:03d} (1987).cbz"


async def _add_issue_file(db, series_id, *, issue_number, cv_issue_id, filename, folder):
    async with db.write_session() as session:
        issue = await repo.create_issue(
            session, series_id=series_id, cv_issue_id=cv_issue_id,
            issue_number=str(issue_number), issue_type="regular",
        )
        path = folder / filename
        path.write_bytes(b"comic-file-contents-well-over-the-junk-floor" * 4)
        row = await repo.add_issue_file(
            session, issue_id=issue.id, path=str(path), size=path.stat().st_size
        )
        return issue.id, row.id, path


async def _inputs(db, series_id):
    async with db.read_session() as session:
        series = await repo.get_series(session, series_id)
        files = await load_rename_inputs(session, series_id)
    return series, files


@pytest.mark.req("FRG-PP-012")
async def test_preview_touches_no_disk(db, seed, import_ctx):
    s = await seed()  # issue "404"
    _, _, wrong = await _add_issue_file(
        db, s.series_id, issue_number=404, cv_issue_id=5001,
        filename="batman #404 dodgy scan.cbz", folder=s.series_path,
    )
    ctx = import_ctx(rename_enabled=True)
    series, files = await _inputs(db, s.series_id)

    before = {p.name: p.stat().st_mtime_ns for p in s.series_path.iterdir()}
    plan = preview_renames(series, files, ctx)
    after = {p.name: p.stat().st_mtime_ns for p in s.series_path.iterdir()}

    assert before == after  # zero create/move/delete/write occurred
    assert len(plan.entries) == 1
    entry = plan.entries[0]
    assert entry.current_path == str(wrong)
    assert entry.changed and Path(entry.new_path).name == _correct_name(404)


@pytest.mark.req("FRG-PP-012")
async def test_execute_performs_exactly_the_previewed_operations(db, seed, import_ctx):
    s = await seed()
    # Two files that must change...
    _, _, a = await _add_issue_file(
        db, s.series_id, issue_number=404, cv_issue_id=5001,
        filename="batman 404 scan.cbz", folder=s.series_path,
    )
    id_b, _, b = await _add_issue_file(
        db, s.series_id, issue_number=405, cv_issue_id=5002,
        filename="Batman #405.cbz", folder=s.series_path,
    )
    # ...and one already at the correct name (must be skipped).
    id_c, _, _tmp = await _add_issue_file(
        db, s.series_id, issue_number=406, cv_issue_id=5003,
        filename="placeholder.cbz", folder=s.series_path,
    )
    correct = s.series_path / _correct_name(406)
    (s.series_path / "placeholder.cbz").rename(correct)
    async with db.write_session() as session:
        row = (
            await session.execute(select(IssueFileRow).where(IssueFileRow.path == str(_tmp)))
        ).scalar_one()
        row.path = str(correct)

    ctx = import_ctx(rename_enabled=True)
    async with db.read_session() as session:
        series = await repo.get_series(session, s.series_id)
    plan = await execute_renames(db, series, ctx)

    assert len(plan.changed) == 2  # only the two differing files are operations
    # The two changed files moved to their previewed new paths; the source names gone.
    assert not a.exists() and not b.exists()
    assert correct.exists()  # the already-correct file was left untouched
    async with db.read_session() as session:
        paths = {
            r.issue_id: r.path
            for r in (await session.execute(select(IssueFileRow))).scalars().all()
        }
    for entry in plan.changed:
        assert paths[entry.issue_id] == entry.new_path  # issue_files.path updated
        assert Path(entry.new_path).exists()
    assert paths[id_c] == str(correct)  # unchanged row keeps its path


@pytest.mark.req("FRG-PP-012")
@pytest.mark.req("FRG-PP-011")
async def test_one_rename_event_per_renamed_file_in_the_same_transaction(
    db, seed, import_ctx
):
    s = await seed()
    for n, cv in ((404, 5001), (405, 5002), (406, 5003)):
        await _add_issue_file(
            db, s.series_id, issue_number=n, cv_issue_id=cv,
            filename=f"wrong-{n}.cbz", folder=s.series_path,
        )
    ctx = import_ctx(rename_enabled=True)
    async with db.read_session() as session:
        series = await repo.get_series(session, s.series_id)
    await execute_renames(db, series, ctx)

    async with db.read_session() as session:
        events = await history.all_events(session)
    renamed = [e for e in events if e.event_type == history.EVENT_FILE_RENAMED]
    assert len(renamed) == 3  # one per renamed file
    for e in renamed:
        data = history.decode_data(e.data)
        assert data["old_path"] and data["new_path"] and data["old_path"] != data["new_path"]
        assert e.series_id == s.series_id


@pytest.mark.req("FRG-PP-012")
async def test_template_change_bulk_preview_marks_no_ops_unchanged(db, seed, import_ctx):
    s = await seed()
    # A file already matching the current template → unchanged.
    id_ok, _, _ = await _add_issue_file(
        db, s.series_id, issue_number=404, cv_issue_id=5001, filename="tmp.cbz",
        folder=s.series_path,
    )
    correct = s.series_path / _correct_name(404)
    (s.series_path / "tmp.cbz").rename(correct)
    async with db.write_session() as session:
        row = (
            await session.execute(select(IssueFileRow).where(IssueFileRow.path.like("%tmp.cbz")))
        ).scalar_one()
        row.path = str(correct)
    # ...and one that differs.
    await _add_issue_file(
        db, s.series_id, issue_number=405, cv_issue_id=5002, filename="off.cbz",
        folder=s.series_path,
    )

    ctx = import_ctx(rename_enabled=True)
    series, files = await _inputs(db, s.series_id)
    plan = preview_renames(series, files, ctx)

    by_changed = {e.changed for e in plan.entries}
    assert by_changed == {True, False}  # a mix
    assert len(plan.changed) == 1  # only the differing file is an operation
    unchanged = [e for e in plan.entries if not e.changed]
    assert unchanged[0].current_path == str(correct)


@pytest.mark.req("FRG-PP-012")
async def test_flow_previews_without_disk_then_executes(db, seed, tmp_path):
    """The SER-owned flow: preview is disk-free, execute applies the moves."""
    from foragerr.library.flows.rename import preview_series_renames, rename_series

    s = await seed()
    await _add_issue_file(
        db, s.series_id, issue_number=404, cv_issue_id=5001,
        filename="messy rip.cbz", folder=s.series_path,
    )
    # ``_build_ctx`` duck-types the settings it's handed (media_management_fields
    # reads by hasattr); a minimal stub with rename_enabled=True is enough to
    # exercise renaming here (ImportContext.rename_enabled now defaults False).
    settings = SimpleNamespace(config_dir=str(tmp_path), rename_enabled=True)

    plan = await preview_series_renames(db, settings, s.series_id)
    assert len(plan.changed) == 1
    assert (s.series_path / "messy rip.cbz").exists()  # preview moved nothing

    result = await rename_series(db, settings, s.series_id)
    assert len(result.changed) == 1
    assert not (s.series_path / "messy rip.cbz").exists()  # executed the move
    assert Path(result.changed[0].new_path).exists()


@pytest.mark.req("FRG-PP-012")
async def test_duplicate_target_blocks_both_files_with_reasons(db, seed, import_ctx):
    """Two files that render the SAME new_path (both linked to one issue) are a
    target collision: applying either move would overwrite the other, so BOTH are
    blocked with a reason and NEITHER file is touched (data-loss guard)."""
    s = await seed()
    async with db.write_session() as session:
        issue = await repo.create_issue(
            session, series_id=s.series_id, cv_issue_id=7001,
            issue_number="600", issue_type="regular",
        )
        x = s.series_path / "scan-x.cbz"
        y = s.series_path / "scan-y.cbz"
        x.write_bytes(b"x" * 256)
        y.write_bytes(b"y" * 256)
        await repo.add_issue_file(session, issue_id=issue.id, path=str(x), size=x.stat().st_size)
        await repo.add_issue_file(session, issue_id=issue.id, path=str(y), size=y.stat().st_size)

    ctx = import_ctx(rename_enabled=True)
    series, files = await _inputs(db, s.series_id)
    plan = preview_renames(series, files, ctx)

    assert len(plan.blocked) == 2  # both competing files blocked, no winner
    assert all(e.reason for e in plan.blocked)
    assert len(plan.changed) == 0  # nothing is an applicable operation

    await execute_renames(db, series, ctx)
    assert x.exists() and y.exists()  # neither file was moved/overwritten
    assert x.read_bytes() == b"x" * 256 and y.read_bytes() == b"y" * 256


@pytest.mark.req("FRG-PP-012")
async def test_swap_chain_renames_both_files_without_byte_loss(db, seed, import_ctx):
    """A swap chain (A→B's path while B→A's path) renames BOTH correctly: the
    two-phase move stages each file at a temp name first, so no ordering lets one
    move clobber a file the other has not yet vacated."""
    s = await seed()
    id1, row_a, tmp_a = await _add_issue_file(
        db, s.series_id, issue_number=500, cv_issue_id=6001,
        filename="tmp-a.cbz", folder=s.series_path,
    )
    id2, row_b, tmp_b = await _add_issue_file(
        db, s.series_id, issue_number=501, cv_issue_id=6002,
        filename="tmp-b.cbz", folder=s.series_path,
    )
    target_a = s.series_path / _correct_name(500)  # fileA's new_path
    target_b = s.series_path / _correct_name(501)  # fileB's new_path
    # Set up the swap: fileA currently sits AT B's target, fileB AT A's target.
    tmp_a.replace(target_b)
    target_b.write_bytes(b"AAA-content")
    tmp_b.replace(target_a)
    target_a.write_bytes(b"BBB-content")
    async with db.write_session() as session:
        (await session.get(IssueFileRow, row_a)).path = str(target_b)
        (await session.get(IssueFileRow, row_b)).path = str(target_a)

    ctx = import_ctx(rename_enabled=True)
    async with db.read_session() as session:
        series = await repo.get_series(session, s.series_id)
    plan = await execute_renames(db, series, ctx)

    assert len(plan.changed) == 2 and not plan.blocked
    # Both files landed at their correct targets with their own bytes intact.
    assert target_a.read_bytes() == b"AAA-content"
    assert target_b.read_bytes() == b"BBB-content"
    async with db.read_session() as session:
        paths = {
            r.issue_id: r.path
            for r in (await session.execute(select(IssueFileRow))).scalars().all()
        }
    assert paths[id1] == str(target_a) and paths[id2] == str(target_b)


@pytest.mark.req("FRG-PP-012")
async def test_mid_batch_vanished_file_isolates_to_that_file(db, seed, import_ctx):
    """A file that vanishes before its move fails ONLY itself: every other file
    still renames and keeps its committed row (per-file isolation), instead of the
    old all-or-nothing transaction rolling back durable rows."""
    s = await seed()
    id_ok, _, ok_file = await _add_issue_file(
        db, s.series_id, issue_number=700, cv_issue_id=8001,
        filename="wrong-700.cbz", folder=s.series_path,
    )
    id_gone, _, gone_file = await _add_issue_file(
        db, s.series_id, issue_number=701, cv_issue_id=8002,
        filename="wrong-701.cbz", folder=s.series_path,
    )
    async with db.read_session() as session:
        series = await repo.get_series(session, s.series_id)
    gone_file.unlink()  # vanishes before execution

    ctx = import_ctx(rename_enabled=True)
    await execute_renames(db, series, ctx)

    # The healthy file renamed and its row was committed-updated...
    ok_target = s.series_path / _correct_name(700)
    assert ok_target.exists() and not ok_file.exists()
    async with db.read_session() as session:
        paths = {
            r.issue_id: r.path
            for r in (await session.execute(select(IssueFileRow))).scalars().all()
        }
    assert paths[id_ok] == str(ok_target)  # earlier file kept its committed row
    assert paths[id_gone] == str(gone_file)  # vanished file's row left untouched


@pytest.mark.req("FRG-PP-012")
@pytest.mark.req("FRG-PP-009")
async def test_every_previewed_name_round_trips(db, seed, import_ctx):
    s = await seed()
    _, _, _ = await _add_issue_file(
        db, s.series_id, issue_number=404, cv_issue_id=5001,
        filename="batman 404 rescan.cbz", folder=s.series_path,
    )
    # This test's subject includes the internal-id tag round-tripping (below),
    # which the shipped tag-free default (FRG-PP-020) no longer carries — pin
    # the tagged template explicitly so that coverage stays exercised.
    ctx = import_ctx(
        rename_enabled=True,
        file_template="{Series Title} {Issue Number:000} ({Year}) [__{IssueId}__]",
    )
    series, files = await _inputs(db, s.series_id)
    plan = preview_renames(series, files, ctx)

    entry = plan.entries[0]
    reparsed = parse(Path(entry.new_path).name, reference_year=2026)
    assert reparsed.success and reparsed.issue is not None
    # Recovers the same series matching key and issue ordering key as the source.
    assert reparsed.matching_key == matching_key("Batman")
    expected = encode_sort_key(sort_key(Issue(value=Fraction(404), display="404")))
    assert encode_sort_key(sort_key(reparsed.issue)) == expected
    assert reparsed.issue_id == str(entry.issue_id)  # id tag preserved
