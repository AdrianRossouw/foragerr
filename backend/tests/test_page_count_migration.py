"""OPDS-PSE schema (migration 0012): ``issue_files.page_count`` caches the
archive's image-page count for ``pse:count`` (FRG-OPDS-009). Nullable and
additive: legacy/scan rows stay NULL and are resolved lazily on first OPDS
access. Forward-only (FRG-DB-002)."""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-OPDS-009")
def test_issue_files_page_count_column_present_and_nullable(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0012_issue_file_page_count" in result.applied
    assert current_revision(db_path) == result.head_revision

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]: row for row in conn.execute("PRAGMA table_info(issue_files)")
        }
        # A legacy-shaped row (no page_count) still inserts: NULL = not yet
        # computed; the OPDS path resolves it lazily on first access.
        conn.execute(
            "INSERT INTO issues (series_id, cv_issue_id, issue_number, "
            "ordering_key, issue_type, monitored, added_at) "
            "VALUES (1, 1, '1', 'k', 'regular', 1, '2026-07-08T00:00:00')"
        )
        conn.execute(
            "INSERT INTO issue_files (issue_id, path, size, added_at) "
            "VALUES (1, '/lib/a.cbz', 10, '2026-07-08T00:00:00')"
        )
        row = conn.execute(
            "SELECT page_count FROM issue_files WHERE path='/lib/a.cbz'"
        ).fetchone()

    assert "page_count" in columns
    assert columns["page_count"][3] == 0  # nullable
    assert row == (None,)
