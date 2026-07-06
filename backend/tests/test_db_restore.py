"""Startup restore-from-marker hook + no live-restore endpoint (FRG-DB-010)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from foragerr.config import Settings
from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.backup import write_scheduled_backup
from foragerr.db.backup_command import restore_marker_startup_hook
from foragerr.db.restore import RESTORE_MARKER_NAME, apply_restore_marker


def _prepared(tmp_path: Path) -> Path:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    (cfg / "config.yaml").write_text("port: 8789\n", encoding="utf-8")
    return cfg


def _set_probe(db_path: Path, value: str, *, create: bool = False) -> None:
    conn = sqlite3.connect(db_path)
    try:
        if create:
            conn.execute("CREATE TABLE probe (v TEXT)")
            conn.execute("INSERT INTO probe VALUES (?)", (value,))
        else:
            conn.execute("UPDATE probe SET v = ?", (value,))
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _read_probe(db_path: Path) -> str:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT v FROM probe").fetchone()[0]
    finally:
        conn.close()


@pytest.mark.req("FRG-DB-010")
def test_marker_restores_to_the_backup_point(tmp_path):
    cfg = _prepared(tmp_path)
    live_db = cfg / DB_FILENAME
    _set_probe(live_db, "v1", create=True)

    backup = write_scheduled_backup(
        live_db, cfg / "config.yaml", cfg, retention=7
    )
    # Diverge the live database AFTER the backup.
    _set_probe(live_db, "v2")
    assert _read_probe(live_db) == "v2"

    (cfg / RESTORE_MARKER_NAME).write_text(backup.name, encoding="utf-8")
    result = apply_restore_marker(cfg)

    assert result is not None and result.status == "restored"
    assert _read_probe(live_db) == "v1"  # reflects the backup point
    assert not (cfg / RESTORE_MARKER_NAME).exists()  # marker cleared (no loop)
    # The pre-restore snapshot preserves the divergent live state.
    assert result.snapshot_dir is not None
    assert _read_probe(result.snapshot_dir / DB_FILENAME) == "v2"


@pytest.mark.req("FRG-DB-010")
def test_no_marker_is_a_noop(tmp_path):
    cfg = _prepared(tmp_path)
    _set_probe(cfg / DB_FILENAME, "live", create=True)
    assert apply_restore_marker(cfg) is None
    assert _read_probe(cfg / DB_FILENAME) == "live"


@pytest.mark.req("FRG-DB-010")
@pytest.mark.parametrize("target", ["../../etc/passwd", "/etc", "../secret"])
def test_hostile_target_is_refused_live_untouched(tmp_path, target):
    cfg = _prepared(tmp_path)
    live_db = cfg / DB_FILENAME
    _set_probe(live_db, "live", create=True)
    (cfg / RESTORE_MARKER_NAME).write_text(target, encoding="utf-8")

    result = apply_restore_marker(cfg)

    assert result is not None and result.status == "refused"
    assert _read_probe(live_db) == "live"  # byte-for-byte untouched, no swap


@pytest.mark.req("FRG-DB-010")
def test_corrupt_backup_is_refused(tmp_path):
    cfg = _prepared(tmp_path)
    live_db = cfg / DB_FILENAME
    _set_probe(live_db, "live", create=True)

    bad = cfg / "backups" / "scheduled-corrupt"
    bad.mkdir(parents=True)
    (bad / DB_FILENAME).write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
    (cfg / RESTORE_MARKER_NAME).write_text("scheduled-corrupt", encoding="utf-8")

    result = apply_restore_marker(cfg)

    assert result is not None and result.status == "refused"
    assert _read_probe(live_db) == "live"  # untouched


@pytest.mark.req("FRG-DB-010")
def test_copy_failure_leaves_live_db_byte_identical(tmp_path, monkeypatch):
    """An operational failure during the swap copy leaves the live DB byte-for-
    byte unchanged (staged temp + atomic rename, never a torn overwrite) and
    KEEPS the marker for a retry."""
    import foragerr.db.restore as restore_mod

    cfg = _prepared(tmp_path)
    live_db = cfg / DB_FILENAME
    _set_probe(live_db, "live", create=True)
    backup = write_scheduled_backup(live_db, cfg / "config.yaml", cfg, retention=7)
    _set_probe(live_db, "diverged")  # live now differs from the backup point
    before = live_db.read_bytes()
    (cfg / RESTORE_MARKER_NAME).write_text(backup.name, encoding="utf-8")

    # Snapshot succeeds; the swap copy fails.
    def boom(_src, _dst):
        raise OSError("disk full during swap")

    monkeypatch.setattr(restore_mod, "_stage_copy", boom)

    result = apply_restore_marker(cfg)

    assert result is not None and result.status == "failed"
    assert live_db.read_bytes() == before  # byte-identical — no torn write
    assert (cfg / RESTORE_MARKER_NAME).exists()  # marker KEPT for a retry


@pytest.mark.req("FRG-DB-010")
async def test_startup_hook_survives_operational_restore_failure(tmp_path, monkeypatch):
    """A disk-full-style snapshot/swap failure does not raise out of the startup
    hook (no boot loop): the hook returns, the live DB is intact, marker kept."""
    import foragerr.db.restore as restore_mod

    cfg = _prepared(tmp_path)
    live_db = cfg / DB_FILENAME
    _set_probe(live_db, "live", create=True)
    backup = write_scheduled_backup(live_db, cfg / "config.yaml", cfg, retention=7)
    _set_probe(live_db, "live2")
    before = live_db.read_bytes()
    (cfg / RESTORE_MARKER_NAME).write_text(backup.name, encoding="utf-8")

    def boom(_src, _dst):
        raise OSError("no space left on device")

    monkeypatch.setattr(restore_mod, "_stage_copy", boom)

    app = SimpleNamespace(state=SimpleNamespace(settings=Settings(config_dir=cfg)))
    await restore_marker_startup_hook(app)  # returns normally — no raise

    assert live_db.read_bytes() == before  # live DB intact
    assert (cfg / RESTORE_MARKER_NAME).exists()  # marker kept for a retry


@pytest.mark.req("FRG-DB-010")
def test_symlinked_backup_file_escaping_root_is_refused(tmp_path):
    """A backup dir inside the root whose DB file is a symlink escaping the root
    is refused (the resolved FILE, not just the dir, is confined)."""
    cfg = _prepared(tmp_path)
    live_db = cfg / DB_FILENAME
    _set_probe(live_db, "live", create=True)
    before = live_db.read_bytes()

    outside = tmp_path / "outside.db"
    _set_probe(outside, "evil", create=True)
    bad = cfg / "backups" / "scheduled-symlinkescape"
    bad.mkdir(parents=True)
    (bad / DB_FILENAME).symlink_to(outside)
    (cfg / RESTORE_MARKER_NAME).write_text("scheduled-symlinkescape", encoding="utf-8")

    result = apply_restore_marker(cfg)

    assert result is not None and result.status == "refused"
    assert live_db.read_bytes() == before  # untouched, no swap


@pytest.mark.req("FRG-DB-010")
def test_no_live_restore_endpoint(tmp_path):
    """No route swaps the live database at runtime — restore is offline / marker
    only."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    from foragerr.app import create_app

    app = create_app(Settings(config_dir=cfg))
    paths = [getattr(r, "path", "") for r in app.routes]
    assert not any("restore" in p.lower() for p in paths)
