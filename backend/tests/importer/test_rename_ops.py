"""Rename preview + execute for existing library files (FRG-PP-012).

Covers every delta-spec scenario: a pure disk-free preview, execute applying
exactly the previewed changed moves, one rename event per renamed file in the
caller's transaction, no-op entries marked unchanged and excluded, and the
round-trip contract holding for every previewed name.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

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


def _correct_name(issue_number: int, issue_id: int) -> str:
    """The default-template rendering for a Batman (1987) issue."""
    return f"Batman {issue_number:03d} (1987) [__{issue_id}__].cbz"


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
    ctx = import_ctx()
    series, files = await _inputs(db, s.series_id)

    before = {p.name: p.stat().st_mtime_ns for p in s.series_path.iterdir()}
    plan = preview_renames(series, files, ctx)
    after = {p.name: p.stat().st_mtime_ns for p in s.series_path.iterdir()}

    assert before == after  # zero create/move/delete/write occurred
    assert len(plan.entries) == 1
    entry = plan.entries[0]
    assert entry.current_path == str(wrong)
    assert entry.changed and Path(entry.new_path).name == _correct_name(404, entry.issue_id)


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
    correct = s.series_path / _correct_name(406, id_c)
    (s.series_path / "placeholder.cbz").rename(correct)
    async with db.write_session() as session:
        row = (
            await session.execute(select(IssueFileRow).where(IssueFileRow.path == str(_tmp)))
        ).scalar_one()
        row.path = str(correct)

    ctx = import_ctx()
    async with db.write_session() as session:
        series = await repo.get_series(session, s.series_id)
        plan = await execute_renames(session, series, ctx)

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
    ctx = import_ctx()
    async with db.write_session() as session:
        series = await repo.get_series(session, s.series_id)
        await execute_renames(session, series, ctx)

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
    correct = s.series_path / _correct_name(404, id_ok)
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

    ctx = import_ctx()
    series, files = await _inputs(db, s.series_id)
    plan = preview_renames(series, files, ctx)

    by_changed = {e.changed for e in plan.entries}
    assert by_changed == {True, False}  # a mix
    assert len(plan.changed) == 1  # only the differing file is an operation
    unchanged = [e for e in plan.entries if not e.changed]
    assert unchanged[0].current_path == str(correct)


@pytest.mark.req("FRG-PP-012")
async def test_flow_previews_without_disk_then_executes(db, seed):
    """The SER-owned flow: preview is disk-free, execute applies the moves."""
    from foragerr.library.flows.rename import preview_series_renames, rename_series

    s = await seed()
    await _add_issue_file(
        db, s.series_id, issue_number=404, cv_issue_id=5001,
        filename="messy rip.cbz", folder=s.series_path,
    )

    plan = await preview_series_renames(db, None, s.series_id)
    assert len(plan.changed) == 1
    assert (s.series_path / "messy rip.cbz").exists()  # preview moved nothing

    result = await rename_series(db, None, s.series_id)
    assert len(result.changed) == 1
    assert not (s.series_path / "messy rip.cbz").exists()  # executed the move
    assert Path(result.changed[0].new_path).exists()


@pytest.mark.req("FRG-PP-012")
@pytest.mark.req("FRG-PP-009")
async def test_every_previewed_name_round_trips(db, seed, import_ctx):
    s = await seed()
    _, _, _ = await _add_issue_file(
        db, s.series_id, issue_number=404, cv_issue_id=5001,
        filename="batman 404 rescan.cbz", folder=s.series_path,
    )
    ctx = import_ctx()
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
