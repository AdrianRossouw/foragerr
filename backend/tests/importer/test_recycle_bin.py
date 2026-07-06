"""Recycle bin: user deletion, retention prune, quarantine sweep, confinement
(FRG-PP-013). The upgrade-recycle and no-bin-permanent-delete scenarios live in
``test_pipeline.py`` (they exercise the pipeline execute path)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.importer import fileops, history, recycle
from foragerr.library import repo
from foragerr.library.flows.edit_delete import delete_issue_file
from foragerr.library.models import IssueFileRow

from http_support import make_settings


# --- fileops.recycle_file: confinement + collision-safe naming ---------------


@pytest.mark.req("FRG-PP-013")
def test_recycle_file_destination_is_confined_under_the_bin(tmp_path):
    bin_root = tmp_path / "recycle"
    bin_root.mkdir()
    src = tmp_path / "Batman 001.cbz"
    src.write_bytes(b"payload")

    dest = fileops.recycle_file(src, bin_root, now=dt.datetime(2026, 7, 5))

    assert bin_root in dest.parents  # built via safe_join under the bin root
    assert dest.read_bytes() == b"payload"
    assert not src.exists()  # moved, not copied


@pytest.mark.req("FRG-PP-013")
@pytest.mark.req("FRG-SEC-004")
def test_recycle_confines_a_hostile_source_name_under_the_bin(tmp_path):
    """Driving ``recycle_file`` itself with a traversal-laden source basename: the
    destination is built via ``safe_join`` under the resolved bin root, so a name
    engineered to climb out (``..``/separator lookalikes) is reduced to a single
    safe segment and can never land outside the bin (FRG-SEC-004)."""
    bin_root = tmp_path / "recycle"
    bin_root.mkdir()
    outside = tmp_path / "outside-the-bin"
    outside.mkdir()
    # A real, filesystem-legal basename a malicious archive might carry, whose raw
    # form would escape if joined naively.
    src = tmp_path / "..__..__escape.cbz"
    src.write_bytes(b"payload")

    dest = fileops.recycle_file(src, bin_root, now=dt.datetime(2026, 7, 5))

    resolved = dest.resolve()
    assert bin_root.resolve() in resolved.parents  # confined under the bin root
    assert outside.resolve() not in resolved.parents  # never escaped sideways
    assert dest.read_bytes() == b"payload"
    assert not src.exists()  # moved, not copied


@pytest.mark.req("FRG-PP-013")
def test_recycle_file_collision_safe_numeric_suffix(tmp_path):
    bin_root = tmp_path / "recycle"
    bin_root.mkdir()
    now = dt.datetime(2026, 7, 5)
    for _ in range(2):
        src = tmp_path / "dup.cbz"
        src.write_bytes(b"data")
        fileops.recycle_file(src, bin_root, now=now)
    names = sorted(p.name for p in (bin_root / "2026-07-05").iterdir())
    assert names == ["dup.1.cbz", "dup.cbz"]  # the second never overwrote the first


# --- prune retention (FRG-PP-013) --------------------------------------------


@pytest.mark.req("FRG-PP-013")
def test_prune_removes_only_aged_entries(tmp_path):
    bin_root = tmp_path / "recycle"
    (bin_root / "2020-01-01").mkdir(parents=True)
    (bin_root / "2020-01-01" / "old.cbz").write_bytes(b"old")
    today = dt.date(2026, 7, 5).isoformat()
    (bin_root / today).mkdir()
    (bin_root / today / "new.cbz").write_bytes(b"new")
    (bin_root / fileops.RECYCLE_BIN_MARKER).touch()  # a real foragerr bin

    removed = fileops.prune_recycle_bin(
        bin_root, retention_days=30, now=dt.datetime(2026, 7, 5)
    )

    assert removed == 1
    assert not (bin_root / "2020-01-01").exists()  # aged folder pruned
    assert (bin_root / today / "new.cbz").exists()  # recent one retained
    assert (bin_root / fileops.RECYCLE_BIN_MARKER).exists()  # marker never pruned


@pytest.mark.req("FRG-PP-013")
def test_prune_refuses_a_directory_without_the_bin_marker(tmp_path):
    """A retention prune pointed at a directory that is NOT a foragerr recycle bin
    (no marker) — e.g. a library root full of series folders, some ISO-date-named —
    deletes NOTHING, so housekeeping can never eat a real library."""
    library_root = tmp_path / "library"
    # Series-like folders, including one whose name happens to be an ISO date.
    (library_root / "Batman (1987)").mkdir(parents=True)
    (library_root / "Batman (1987)" / "issue.cbz").write_bytes(b"real")
    (library_root / "2020-01-01").mkdir()  # aged-looking, but no marker present
    (library_root / "2020-01-01" / "keep.cbz").write_bytes(b"real")

    removed = fileops.prune_recycle_bin(
        library_root, retention_days=1, now=dt.datetime(2026, 7, 5)
    )

    assert removed == 0  # refused — not a recycle bin
    assert (library_root / "Batman (1987)" / "issue.cbz").exists()
    assert (library_root / "2020-01-01" / "keep.cbz").exists()  # nothing deleted


@pytest.mark.req("FRG-PP-013")
def test_prune_retention_zero_keeps_everything(tmp_path):
    bin_root = tmp_path / "recycle"
    (bin_root / "2000-01-01").mkdir(parents=True)
    (bin_root / "2000-01-01" / "ancient.cbz").write_bytes(b"a")
    removed = fileops.prune_recycle_bin(bin_root, retention_days=0)
    assert removed == 0
    assert (bin_root / "2000-01-01" / "ancient.cbz").exists()


# --- quarantine → recycle sweep (FRG-PP-013) ---------------------------------


@pytest.mark.req("FRG-PP-013")
async def test_quarantine_files_migrate_without_orphaning_and_idempotent(db, tmp_path):
    config_dir = tmp_path / "config"
    quarantine = config_dir / "quarantine" / "2025-12-01"
    quarantine.mkdir(parents=True)
    (quarantine / "superseded.cbz").write_bytes(b"left-by-m1")
    bin_root = tmp_path / "recycle"
    bin_root.mkdir()

    swept = await recycle.sweep_quarantine_to_recycle(
        db, config_dir=str(config_dir), recycle_bin_path=str(bin_root),
        now=dt.datetime(2026, 7, 5),
    )

    assert swept == 1
    moved = list(bin_root.rglob("superseded.cbz"))
    assert len(moved) == 1 and moved[0].read_bytes() == b"left-by-m1"
    assert not (quarantine / "superseded.cbz").exists()  # none orphaned
    async with db.read_session() as session:
        events = await history.all_events(session)
    assert any(e.event_type == history.EVENT_FILE_DELETED for e in events)

    # Idempotent: a re-run finds nothing to sweep.
    again = await recycle.sweep_quarantine_to_recycle(
        db, config_dir=str(config_dir), recycle_bin_path=str(bin_root),
        now=dt.datetime(2026, 7, 5),
    )
    assert again == 0


@pytest.mark.req("FRG-PP-013")
async def test_quarantine_left_in_place_when_no_bin_configured(db, tmp_path):
    config_dir = tmp_path / "config"
    quarantine = config_dir / "quarantine" / "2025-12-01"
    quarantine.mkdir(parents=True)
    (quarantine / "keep.cbz").write_bytes(b"retired-in-place")

    swept = await recycle.sweep_quarantine_to_recycle(
        db, config_dir=str(config_dir), recycle_bin_path=""
    )

    assert swept == 0
    assert (quarantine / "keep.cbz").exists()  # retired, never deleted


# --- user deletion routes through the bin (FRG-PP-013) -----------------------


async def _seed_file(db, seed, name: str) -> tuple[int, Path]:
    s = await seed()
    path = s.series_path / name
    path.write_bytes(b"a-real-library-file")
    async with db.write_session() as session:
        row = await repo.add_issue_file(
            session, issue_id=s.issue_id, path=str(path), size=path.stat().st_size
        )
        return row.id, path


@pytest.mark.req("FRG-PP-013")
async def test_user_deletion_routes_through_the_bin(db, seed, library_root, tmp_path):
    file_id, path = await _seed_file(db, seed, "Batman 010.cbz")
    bin_root = tmp_path / "recycle"
    bin_root.mkdir()
    settings = make_settings(tmp_path / "cfg", recycle_bin_path=str(bin_root))
    (tmp_path / "cfg").mkdir(exist_ok=True)

    recycle_path = await delete_issue_file(db, settings, file_id, now=dt.datetime(2026, 7, 5))

    assert recycle_path is not None
    assert bin_root in Path(recycle_path).parents
    assert not path.exists()  # never hard-deleted
    assert Path(recycle_path).read_bytes() == b"a-real-library-file"
    async with db.read_session() as session:
        remaining = (await session.execute(select(IssueFileRow))).scalars().all()
        events = await history.all_events(session)
    assert remaining == []  # the issue_files row was removed (issue → Wanted)
    deleted = [e for e in events if e.event_type == history.EVENT_FILE_DELETED]
    assert len(deleted) == 1 and deleted[0].quarantine_path == recycle_path
    # Default provenance is MANUAL — deleting a library file is a user action,
    # not a rescan (m2-daily-surfaces, the series-detail screen requirement).
    assert deleted[0].source == history.SOURCE_MANUAL


@pytest.mark.req("FRG-PP-013")
async def test_user_deletion_without_bin_deletes_permanently(db, seed, library_root, tmp_path):
    file_id, path = await _seed_file(db, seed, "Batman 011.cbz")
    settings = make_settings(tmp_path / "cfg")  # no recycle bin

    recycle_path = await delete_issue_file(db, settings, file_id)

    assert recycle_path is None
    assert not path.exists()  # permanently deleted
    async with db.read_session() as session:
        events = await history.all_events(session)
    deleted = [e for e in events if e.event_type == history.EVENT_FILE_DELETED]
    assert len(deleted) == 1 and deleted[0].quarantine_path is None


@pytest.mark.req("FRG-PP-013")
async def test_recycle_deletion_compensates_when_the_commit_fails(
    db, seed, library_root, tmp_path, monkeypatch
):
    """The file is moved to the bin BEFORE the row-removal transaction; if that
    transaction fails the move is COMPENSATED (file restored to its original
    path), so a commit failure never leaves a live row pointing at a moved file."""
    from foragerr.library.flows import edit_delete

    file_id, path = await _seed_file(db, seed, "Batman 012.cbz")
    bin_root = tmp_path / "recycle"
    bin_root.mkdir()
    (tmp_path / "cfg").mkdir(exist_ok=True)
    settings = make_settings(tmp_path / "cfg", recycle_bin_path=str(bin_root))

    async def boom(session, issue_file_id):
        raise RuntimeError("row removal failed mid-commit")

    monkeypatch.setattr(edit_delete.repo, "remove_issue_file", boom)

    with pytest.raises(RuntimeError):
        await delete_issue_file(db, settings, file_id, now=dt.datetime(2026, 7, 5))

    assert path.exists()  # compensated: file moved back out of the bin
    assert path.read_bytes() == b"a-real-library-file"
    assert not list(bin_root.rglob("*.cbz"))  # the staged copy was moved back
    async with db.read_session() as session:
        remaining = (await session.execute(select(IssueFileRow))).scalars().all()
    assert len(remaining) == 1  # row survived — never orphaned a moved file


@pytest.mark.req("FRG-PP-013")
async def test_permanent_delete_commits_row_before_unlinking(
    db, seed, library_root, tmp_path, monkeypatch
):
    """With no bin, the row removal + event COMMIT first and the file is unlinked
    only AFTER; a post-commit unlink failure orphans the file on disk (recoverable)
    rather than leaving a dangling row pointing at a live file."""
    from foragerr.library.flows import edit_delete

    file_id, path = await _seed_file(db, seed, "Batman 013.cbz")
    settings = make_settings(tmp_path / "cfg")  # no recycle bin

    def boom(target):
        raise OSError("unlink denied")

    monkeypatch.setattr(edit_delete.os, "remove", boom)

    result = await delete_issue_file(db, settings, file_id)

    assert result is None
    async with db.read_session() as session:
        remaining = (await session.execute(select(IssueFileRow))).scalars().all()
    assert remaining == []  # row removed even though the unlink failed
    assert path.exists()  # file orphaned on disk (recoverable), never a dangling row
