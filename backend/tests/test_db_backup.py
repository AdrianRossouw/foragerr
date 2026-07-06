"""Scheduled-backup primitives: consistent copy + independent pool retention
(FRG-DB-009)."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.backup import (
    PRE_MIGRATION_PREFIX,
    SCHEDULED_PREFIX,
    latest_scheduled_backup,
    prune_backup_pool,
    write_consistent_backup,
    write_scheduled_backup,
)


def _migrated_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    return cfg


@pytest.mark.req("FRG-DB-009")
def test_scheduled_backup_writes_timestamped_db_and_config(tmp_path):
    cfg = _migrated_config(tmp_path)
    db_path = cfg / DB_FILENAME
    config_path = cfg / "config.yaml"
    config_path.write_text("port: 8789\n", encoding="utf-8")

    target = write_scheduled_backup(db_path, config_path, cfg, retention=7)

    assert target.name.startswith(SCHEDULED_PREFIX)
    assert (target / DB_FILENAME).exists()
    assert (target / "config.yaml").read_text(encoding="utf-8") == "port: 8789\n"
    # The copy is a real, consistent database.
    with sqlite3.connect(target / DB_FILENAME) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.req("FRG-DB-009")
def test_consistent_backup_reflects_uncheckpointed_wal(tmp_path):
    """A backup taken with live WAL content is internally consistent and holds
    every pre-backup commit — proving the checkpoint+backup path, not a torn
    file copy."""
    cfg = _migrated_config(tmp_path)
    db_path = cfg / DB_FILENAME
    # Write a row and leave it in the WAL (do NOT checkpoint) via a separate
    # connection kept open.
    live = sqlite3.connect(db_path)
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("CREATE TABLE probe (v TEXT)")
    live.execute("INSERT INTO probe VALUES ('committed-before-backup')")
    live.commit()
    try:
        dest = tmp_path / "dest"
        dest.mkdir()
        backup_db = write_consistent_backup(db_path, dest)
    finally:
        live.close()

    with sqlite3.connect(backup_db) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        rows = conn.execute("SELECT v FROM probe").fetchall()
    assert rows == [("committed-before-backup",)]


@pytest.mark.req("FRG-DB-009")
def test_retention_prunes_only_scheduled_pool(tmp_path):
    """Scheduled retention prunes only ``scheduled-*`` and never touches a
    ``pre-migration-*`` backup — the two pools retain independently."""
    cfg = _migrated_config(tmp_path)
    db_path = cfg / DB_FILENAME
    config_path = cfg / "config.yaml"
    config_path.write_text("x: 1\n", encoding="utf-8")
    backups_root = cfg / "backups"
    backups_root.mkdir(exist_ok=True)

    # A pre-migration backup that must survive scheduled pruning.
    premig = backups_root / f"{PRE_MIGRATION_PREFIX}aaa-20200101000000"
    premig.mkdir()

    # Five scheduled backups written with ample retention, then given strictly
    # increasing mtimes so pruning order is deterministic (real backups are a
    # day apart; the sub-millisecond test cadence would otherwise tie mtimes).
    now = time.time()
    for i in range(5):
        target = write_scheduled_backup(db_path, config_path, cfg, retention=99)
        os.utime(target, (now + i, now + i))

    prune_backup_pool(backups_root, SCHEDULED_PREFIX, 3)

    scheduled = sorted(backups_root.glob(f"{SCHEDULED_PREFIX}*"))
    assert len(scheduled) == 3  # exactly the retention count remain
    assert premig.exists()  # the pre-migration pool is untouched


@pytest.mark.req("FRG-DB-009")
def test_latest_scheduled_backup_picks_newest(tmp_path):
    cfg = _migrated_config(tmp_path)
    assert latest_scheduled_backup(cfg) is None
    db_path = cfg / DB_FILENAME
    config_path = cfg / "config.yaml"
    config_path.write_text("x: 1\n", encoding="utf-8")

    first = write_scheduled_backup(db_path, config_path, cfg, retention=7)
    now = time.time()
    os.utime(first, (now - 100, now - 100))
    second = write_scheduled_backup(db_path, config_path, cfg, retention=7)
    os.utime(second, (now, now))

    assert latest_scheduled_backup(cfg) == second
