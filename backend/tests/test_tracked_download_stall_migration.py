"""``tracked_downloads`` stall memory (migration 0028): the two columns the
completed-download retry loop needs to be able to escalate (FRG-DL-015).

``import_stall_count`` is NOT NULL with a server default of 0 (a pre-0028 row
has recorded no stalls — the honest starting point, and the value the health
threshold compares against); ``first_stalled_at`` is nullable because "not
stalling" must never be asserted as a time. Additive, forward-only (FRG-DB-002).
"""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-DL-015")
def test_stall_memory_columns_are_present_with_the_right_nullability(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0028_tracked_download_stall_memory" in result.applied
    # Single head: the chain runs to one head and the DB is stamped at it.
    assert current_revision(db_path) == result.head_revision

    with sqlite3.connect(db_path) as conn:
        cols = {
            row[1]: row for row in conn.execute("PRAGMA table_info(tracked_downloads)")
        }
    assert cols["import_stall_count"][2].upper() == "INTEGER"
    assert cols["import_stall_count"][3] == 1  # NOT NULL
    assert cols["import_stall_count"][4] == "'0'"
    assert cols["first_stalled_at"][2].upper() == "DATETIME"
    assert cols["first_stalled_at"][3] == 0  # NULLABLE


@pytest.mark.req("FRG-DL-015")
def test_a_legacy_shaped_row_reads_as_never_stalled(tmp_path):
    """The upgrade shape: a tracked row written without the columns inserts and
    reads back 0 / NULL — never-stalled, never escalated."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO tracked_downloads (download_id, protocol, source, state, "
            "status, added_at, updated_at) VALUES ('legacy', 'usenet', 'indexer', "
            "'import_blocked', 'warning', '2026-07-28 00:00:00', "
            "'2026-07-28 00:00:00')"
        )
        row = conn.execute(
            "SELECT import_stall_count, first_stalled_at FROM tracked_downloads"
        ).fetchone()

    assert row == (0, None)
