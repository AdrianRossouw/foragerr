"""Gate-fix schema (migration 0008): ``issue_files.fix_revision`` persists the
imported file's `(fN)` fixed-release marker (FRG-PP-014) so renaming — which
strips the marker from the placed basename — can never evaporate the
fixed-releases-always-win guarantee. Nullable and additive: legacy rows stay
NULL and the duplicate evaluation falls back to the stored-basename parse."""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-PP-014")
def test_issue_files_fix_revision_column_present_and_nullable(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0008_issue_file_fix_revision" in result.applied
    assert current_revision(db_path) == result.head_revision

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]: row for row in conn.execute("PRAGMA table_info(issue_files)")
        }
        # A legacy-shaped row (no fix_revision) still inserts: NULL = unfixed
        # or predating the column; the read side falls back to basename parse.
        conn.execute(
            "INSERT INTO issues (series_id, cv_issue_id, issue_number, "
            "ordering_key, issue_type, monitored, added_at) "
            "VALUES (1, 1, '1', 'k', 'regular', 1, '2026-07-06T00:00:00')"
        )
        conn.execute(
            "INSERT INTO issue_files (issue_id, path, size, added_at) "
            "VALUES (1, '/lib/a.cbz', 10, '2026-07-06T00:00:00')"
        )
        row = conn.execute(
            "SELECT fix_revision FROM issue_files WHERE path='/lib/a.cbz'"
        ).fetchone()

    assert "fix_revision" in columns
    assert columns["fix_revision"][3] == 0  # nullable
    assert row == (None,)
