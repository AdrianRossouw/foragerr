"""series collected-edition typing schema (migration 0014): the two additive
``series`` columns ``booktype`` (nullable Text) and ``booktype_locked``
(defaulted bool). Additive: a legacy-shaped series insert (omitting both) still
works — ``booktype`` is NULL (single-issues) and ``booktype_locked`` defaults 0.
No CHECK-constraint change, no ``wanted`` column (the schema-hygiene guard stays
green). Forward-only (FRG-DB-002). (FRG-SER-018)"""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-SER-018")
def test_series_booktype_columns_present_with_legacy_insert(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0014_series_booktype" in result.applied
    assert current_revision(db_path) == result.head_revision

    with sqlite3.connect(db_path) as conn:
        series_cols = {row[1]: row for row in conn.execute("PRAGMA table_info(series)")}
        assert "booktype" in series_cols
        assert "booktype_locked" in series_cols
        assert series_cols["booktype"][3] == 0  # nullable
        # No stored wanted column snuck in alongside the typing columns.
        assert "wanted" not in series_cols

        # A root folder + the seeded default profile back the series FK columns.
        conn.execute("INSERT INTO root_folders (id, path) VALUES (1, '/lib')")
        profile_id = conn.execute("SELECT id FROM format_profiles LIMIT 1").fetchone()[0]

        # Legacy-shaped series insert: omit booktype AND booktype_locked.
        conn.execute(
            "INSERT INTO series (cv_volume_id, title, sort_title, matching_key, "
            "status, monitored, monitor_new_items, format_profile_id, "
            "root_folder_id, path, added_at) "
            "VALUES (1, 'Saga (2012)', 'Saga (2012)', 'saga', 'continuing', "
            f"1, 'all', {profile_id}, 1, '/lib/Saga (2012)', "
            "'2026-07-08T00:00:00')"
        )
        row = conn.execute(
            "SELECT booktype, booktype_locked FROM series WHERE cv_volume_id=1"
        ).fetchone()
        assert row == (None, 0)  # NULL type (single-issues), default-unlocked

        # A trade-typed insert round-trips its lowercased Booktype value + lock.
        conn.execute(
            "INSERT INTO series (cv_volume_id, title, sort_title, matching_key, "
            "status, monitored, monitor_new_items, format_profile_id, "
            "root_folder_id, path, added_at, booktype, booktype_locked) "
            "VALUES (2, 'Saga Deluxe HC', 'Saga Deluxe HC', 'saga deluxe hc', "
            f"'continuing', 1, 'all', {profile_id}, 1, '/lib/Saga Deluxe HC', "
            "'2026-07-08T00:00:00', 'hc', 1)"
        )
        typed = conn.execute(
            "SELECT booktype, booktype_locked FROM series WHERE cv_volume_id=2"
        ).fetchone()
        assert typed == ("hc", 1)
