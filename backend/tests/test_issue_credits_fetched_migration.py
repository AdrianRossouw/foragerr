"""issues.credits_fetched_at bookkeeping column (migration 0017): one additive
nullable DATETIME on ``issues`` plus a partial index over the credit-needing
(``NULL``) rows. Forward-only (FRG-DB-002); no data backfill (``NULL`` = needs
fetch is correct for every existing row). FRG-CRTR-002."""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-CRTR-002")
def test_credits_fetched_at_column_and_partial_index_present(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0017_issue_credits_fetched" in result.applied
    assert current_revision(db_path) == result.head_revision

    with sqlite3.connect(db_path) as conn:
        cols = {row[1]: row for row in conn.execute("PRAGMA table_info(issues)")}
        assert "credits_fetched_at" in cols
        # Nullable (no NOT NULL) and no default — a fresh issue is credit-needing.
        assert cols["credits_fetched_at"][3] == 0  # notnull flag off

        indexes = {row[1] for row in conn.execute("PRAGMA index_list(issues)")}
        assert "ix_issues_credits_needed" in indexes

        # The index is partial (has a WHERE clause) — verify via the schema SQL.
        idx_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='ix_issues_credits_needed'"
        ).fetchone()[0]
        assert "WHERE" in idx_sql.upper()
        assert "credits_fetched_at" in idx_sql

        # Existing rows are legal with the column left NULL (no backfill needed).
        conn.execute("INSERT INTO root_folders (id, path) VALUES (1, '/lib')")
        profile_id = conn.execute("SELECT id FROM format_profiles LIMIT 1").fetchone()[0]
        conn.execute(
            "INSERT INTO series (id, cv_volume_id, title, sort_title, matching_key, "
            "status, monitored, monitor_new_items, format_profile_id, root_folder_id, "
            "path, added_at) VALUES (1, 10, 's', 's', 's', 'continuing', 1, 'all', "
            f"{profile_id}, 1, '/lib/s', '2026-07-11T00:00:00')"
        )
        conn.execute(
            "INSERT INTO issues (id, series_id, cv_issue_id, issue_number, "
            "ordering_key, issue_type, monitored, added_at) "
            "VALUES (100, 1, 1000, '1', 'k1', 'regular', 1, '2026-07-11T00:00:00')"
        )
        row = conn.execute(
            "SELECT credits_fetched_at FROM issues WHERE id=100"
        ).fetchone()
        assert row == (None,)
