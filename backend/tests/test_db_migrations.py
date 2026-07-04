"""Migration guard, upgrade, and pre-migration backup (FRG-DB-002/003/004)."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import textwrap
import time
from pathlib import Path

import pytest

from foragerr.db import (
    DB_FILENAME,
    MigrationError,
    SchemaVersionError,
    prepare_database,
)
from foragerr.db.migrations import ALEMBIC_DIR, app_version, current_revision


def _write_chain(dest: Path, *, fail_b: bool = False, only_a: bool = False) -> Path:
    """A fixture migration chain aaa -> bbb (optionally failing at bbb)."""
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(ALEMBIC_DIR / "env.py", dest / "env.py")
    versions = dest / "versions"
    versions.mkdir(exist_ok=True)
    (versions / "rev_a.py").write_text(
        textwrap.dedent(
            """
            import sqlalchemy as sa
            from alembic import op

            revision = "aaa"
            down_revision = None
            branch_labels = None
            depends_on = None

            def upgrade():
                op.create_table(
                    "marker",
                    sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("step", sa.Text(), nullable=False),
                )
                op.execute("INSERT INTO marker(step) VALUES ('a')")

            def downgrade():
                raise NotImplementedError
            """
        ),
        encoding="utf-8",
    )
    if not only_a:
        body = (
            'raise RuntimeError("boom in bbb")'
            if fail_b
            else "op.execute(\"INSERT INTO marker(step) VALUES ('b')\")"
        )
        (versions / "rev_b.py").write_text(
            textwrap.dedent(
                f"""
                import sqlalchemy as sa
                from alembic import op

                revision = "bbb"
                down_revision = "aaa"
                branch_labels = None
                depends_on = None

                def upgrade():
                    {body}

                def downgrade():
                    raise NotImplementedError
                """
            ),
            encoding="utf-8",
        )
    return dest


def _marker_steps(db_path: Path) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        return [r[0] for r in conn.execute("SELECT step FROM marker ORDER BY id")]


@pytest.mark.req("FRG-DB-002")
def test_empty_database_migrates_base_to_head(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert db_path.exists()
    assert result.previous_revision is None
    assert result.applied  # the full chain ran
    assert current_revision(db_path) == result.head_revision
    with sqlite3.connect(db_path) as conn:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"commands", "scheduled_tasks", "job_history"} <= tables


@pytest.mark.req("FRG-DB-002")
@pytest.mark.req("FRG-DB-003")
def test_restart_at_head_is_noop_and_takes_no_backup(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    revision_before = current_revision(cfg / DB_FILENAME)

    result = prepare_database(cfg)

    assert result.applied == []
    assert result.backup_dir is None
    assert current_revision(cfg / DB_FILENAME) == revision_before
    assert not (cfg / "backups").exists()  # no backup dir at head


@pytest.mark.req("FRG-DB-002")
def test_pending_migrations_apply_exactly_once(tmp_path):
    chain_a = _write_chain(tmp_path / "chain_a", only_a=True)
    chain_ab = _write_chain(tmp_path / "chain_ab")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg, script_location=chain_a)  # DB stamped at 'aaa'

    result = prepare_database(cfg, script_location=chain_ab)

    assert result.previous_revision == "aaa"
    assert result.applied == ["bbb"]  # only the pending revision, in order
    assert current_revision(cfg / DB_FILENAME) == "bbb"
    assert _marker_steps(cfg / DB_FILENAME) == ["a", "b"]  # each ran exactly once

    again = prepare_database(cfg, script_location=chain_ab)
    assert again.applied == []
    assert _marker_steps(cfg / DB_FILENAME) == ["a", "b"]  # still exactly once


@pytest.mark.req("FRG-DB-002")
def test_failed_migration_names_revision_and_does_not_stamp(tmp_path):
    chain_a = _write_chain(tmp_path / "chain_a", only_a=True)
    chain_fail = _write_chain(tmp_path / "chain_fail", fail_b=True)
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg, script_location=chain_a)

    with pytest.raises(MigrationError) as excinfo:
        prepare_database(cfg, script_location=chain_fail)

    assert "bbb" in str(excinfo.value)  # failing revision is named
    assert current_revision(cfg / DB_FILENAME) == "aaa"  # last good stamp kept


@pytest.mark.req("FRG-DB-004")
def test_newer_or_unknown_revision_refused_db_untouched(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    db_path = cfg / DB_FILENAME
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE alembic_version SET version_num='ffffffffffff'")
    digest_before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    with pytest.raises(SchemaVersionError) as excinfo:
        prepare_database(cfg)

    message = str(excinfo.value)
    assert "ffffffffffff" in message  # names the DB schema revision
    assert app_version() in message  # names the application version
    digest_after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert digest_after == digest_before  # byte-for-byte unchanged
    assert not (cfg / "backups").exists()  # refusal takes no backup


@pytest.mark.req("FRG-DB-003")
def test_backup_taken_before_migration_is_consistent(tmp_path):
    chain_a = _write_chain(tmp_path / "chain_a", only_a=True)
    chain_ab = _write_chain(tmp_path / "chain_ab")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg, script_location=chain_a)
    db_path = cfg / DB_FILENAME

    # Leave uncheckpointed WAL content behind: a concurrent read transaction
    # stops the closing writer from checkpointing the WAL away.
    writer = sqlite3.connect(db_path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("INSERT INTO marker(step) VALUES ('wal-only-row')")
    writer.commit()
    holder = sqlite3.connect(db_path)
    holder.execute("BEGIN")
    holder.execute("SELECT count(*) FROM marker").fetchone()
    writer.execute("INSERT INTO marker(step) VALUES ('pre-backup-data')")
    writer.commit()
    writer.close()
    assert (cfg / f"{DB_FILENAME}-wal").exists()
    # Release the read snapshot (connection stays open so the WAL persists
    # uncheckpointed) — the backup's own checkpoint must not stall.
    holder.execute("COMMIT")

    result = prepare_database(cfg, script_location=chain_ab)
    holder.close()

    assert result.backup_dir is not None
    assert result.backup_dir.name.startswith("pre-migration-aaa-")
    backup_db = result.backup_dir / DB_FILENAME
    with sqlite3.connect(backup_db) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        steps = [r[0] for r in conn.execute("SELECT step FROM marker ORDER BY id")]
        backup_rev = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    assert "pre-backup-data" in steps  # committed-before-backup data present
    assert "b" not in steps  # reflects the PRE-migration schema/data
    assert backup_rev[0] == "aaa"


@pytest.mark.req("FRG-DB-003")
def test_retention_prunes_oldest_backups(tmp_path):
    chain_a = _write_chain(tmp_path / "chain_a", only_a=True)
    chain_ab = _write_chain(tmp_path / "chain_ab")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg, script_location=chain_a)

    backups_root = cfg / "backups"
    backups_root.mkdir()
    stale = []
    now = time.time()
    for index in range(3):
        d = backups_root / f"pre-migration-old{index}-2020010100000{index}"
        d.mkdir()
        os.utime(d, (now - 1000 + index, now - 1000 + index))
        stale.append(d)

    result = prepare_database(cfg, script_location=chain_ab, retention=3)

    remaining = sorted(p.name for p in backups_root.glob("pre-migration-*"))
    assert len(remaining) == 3  # exactly the retention count remain
    assert result.backup_dir.name in remaining  # the newest is kept
    assert stale[0].name not in remaining  # the oldest was pruned
