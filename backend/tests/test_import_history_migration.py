"""Change-6 schema: the import_history table + quarantine bookkeeping
(FRG-PP-011 — schema only; the behavior that writes/reads it is Wave B)."""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-PP-011")
def test_import_history_table_and_columns_present(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert current_revision(db_path) == "0006_import_history"

    with sqlite3.connect(db_path) as conn:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "import_history" in tables
        columns = {row[1] for row in conn.execute("PRAGMA table_info(import_history)")}
        indexes = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='import_history'"
            )
        }

    assert {
        "id",
        "download_id",
        "series_id",
        "issue_id",
        "event_type",
        "source_title",
        "source",
        "data",
        "quarantine_path",
        "created_at",
    } <= columns
    assert "ix_import_history_download_id" in indexes
    assert "ix_import_history_issue_id" in indexes


@pytest.mark.req("FRG-PP-011")
def test_import_history_accepts_a_rescan_event_without_download_id(tmp_path):
    # download_id is nullable so rescan-sourced events (no download) are storable.
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    db_path = cfg / DB_FILENAME
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO import_history "
            "(download_id, event_type, source, created_at) "
            "VALUES (NULL, 'import_blocked', 'rescan', '2026-07-05T00:00:00')"
        )
        conn.commit()
        row = conn.execute(
            "SELECT download_id, event_type, source FROM import_history"
        ).fetchone()
    assert row == (None, "import_blocked", "rescan")
