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
def test_recycle_destination_is_built_via_safe_join_under_the_bin(tmp_path, monkeypatch):
    """The destination is constructed through ``safe_join`` under the bin root —
    the same confinement guarantee every other destination path uses, so a source
    name engineered to traverse (``..``/absolute) is reduced to a safe segment and
    cannot land outside the bin (FRG-SEC-004)."""
    bin_root = tmp_path / "recycle"
    bin_root.mkdir()
    src = tmp_path / "Batman 001.cbz"
    src.write_bytes(b"x")

    seen: list = []
    real_safe_join = fileops.safe_join

    def spy(root, *parts):
        seen.append((str(root), parts))
        result = real_safe_join(root, *parts)
        # A crafted traversal segment resolves back inside the bin, never outside.
        assert bin_root in Path(result).parents or Path(result) == bin_root
        return result

    monkeypatch.setattr(fileops, "safe_join", spy)
    dest = fileops.recycle_file(src, bin_root, now=dt.datetime(2026, 7, 5))

    assert seen and seen[0][0] == str(bin_root)  # confinement rooted at the bin
    assert bin_root in dest.parents
    # A traversal segment is reduced to a safe component, never a real boundary.
    assert bin_root in real_safe_join(bin_root, "..", "escape.cbz").parents


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

    removed = fileops.prune_recycle_bin(
        bin_root, retention_days=30, now=dt.datetime(2026, 7, 5)
    )

    assert removed == 1
    assert not (bin_root / "2020-01-01").exists()  # aged folder pruned
    assert (bin_root / today / "new.cbz").exists()  # recent one retained


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
