"""trade-containment side table schema (migration 0015): the dedicated
``issue_collections`` table (FRG-SER-020). A pure new table — no column added
to ``series``/``issues`` — with both FKs ``ON DELETE CASCADE``, the source
CHECK, and the two indexes. Forward-only (FRG-DB-002)."""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-SER-020")
def test_issue_collections_table_present_and_cascades(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0015_issue_collections" in result.applied
    assert current_revision(db_path) == result.head_revision

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")

        cols = {row[1]: row for row in conn.execute("PRAGMA table_info(issue_collections)")}
        assert set(cols) == {
            "id",
            "trade_issue_id",
            "target_series_id",
            "start_ordering_key",
            "end_ordering_key",
            "range_label",
            "source",
            "confidence",
            "created_at",
        }
        # Containment lives entirely in the side table: no column leaked onto
        # series/issues.
        series_cols = {row[1] for row in conn.execute("PRAGMA table_info(series)")}
        issue_cols = {row[1] for row in conn.execute("PRAGMA table_info(issues)")}
        assert "collected_in" not in series_cols and "collected_in" not in issue_cols
        assert not (series_cols & {"trade_issue_id", "target_series_id"})

        indexes = {
            row[1] for row in conn.execute("PRAGMA index_list(issue_collections)")
        }
        assert "ix_issue_collections_trade_issue_id" in indexes
        assert "ix_issue_collections_target_series" in indexes

        # Back the FK columns with a real trade issue + target series.
        conn.execute("INSERT INTO root_folders (id, path) VALUES (1, '/lib')")
        profile_id = conn.execute("SELECT id FROM format_profiles LIMIT 1").fetchone()[0]
        for cv_vol, sid in ((10, 1), (20, 2)):
            conn.execute(
                "INSERT INTO series (id, cv_volume_id, title, sort_title, "
                "matching_key, status, monitored, monitor_new_items, "
                "format_profile_id, root_folder_id, path, added_at, booktype) "
                f"VALUES ({sid}, {cv_vol}, 't{sid}', 't{sid}', 't{sid}', "
                f"'continuing', 1, 'all', {profile_id}, 1, '/lib/t{sid}', "
                "'2026-07-10T00:00:00', 'tpb')"
            )
        conn.execute(
            "INSERT INTO issues (id, series_id, cv_issue_id, issue_number, "
            "ordering_key, issue_type, monitored, added_at) "
            "VALUES (100, 1, 1000, '1', 'k1', 'tpb-content', 1, '2026-07-10T00:00:00')"
        )
        conn.execute(
            "INSERT INTO issue_collections (trade_issue_id, target_series_id, "
            "start_ordering_key, end_ordering_key, range_label, created_at) "
            "VALUES (100, 2, 'a', 'z', '#1–#6', '2026-07-10T00:00:00')"
        )
        # source defaults to 'declared', confidence to 1.0.
        row = conn.execute(
            "SELECT source, confidence FROM issue_collections"
        ).fetchone()
        assert row == ("declared", 1.0)

        # The CHECK rejects an out-of-vocabulary source.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO issue_collections (trade_issue_id, target_series_id, "
                "start_ordering_key, end_ordering_key, range_label, source, "
                "created_at) VALUES (100, 2, 'a', 'z', '#1', 'guessed', "
                "'2026-07-10T00:00:00')"
            )

        # Deleting the target series cascades the record away (nothing else).
        conn.execute("DELETE FROM series WHERE id=2")
        assert conn.execute("SELECT count(*) FROM issue_collections").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM issues").fetchone()[0] == 1
