"""series_groups schema (migration 0013): the franchise-grouping table plus the
two additive ``series`` columns ``series_group_id`` (nullable FK, ON DELETE SET
NULL) and ``group_locked`` (defaulted). Additive: a legacy-shaped series insert
(omitting both) still works — ``series_group_id`` is NULL and ``group_locked``
defaults 0. Forward-only (FRG-DB-002). (FRG-SER-016/017)"""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-SER-016")
@pytest.mark.req("FRG-SER-017")
def test_series_groups_table_and_columns_present_with_legacy_insert(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0013_series_groups" in result.applied
    assert current_revision(db_path) == result.head_revision

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        # New table present.
        group_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(series_groups)")
        }
        assert {"id", "title", "grouping_key", "manual_title", "created_at"} <= group_cols

        series_cols = {
            row[1]: row for row in conn.execute("PRAGMA table_info(series)")
        }
        assert "series_group_id" in series_cols
        assert "group_locked" in series_cols
        assert series_cols["series_group_id"][3] == 0  # nullable

        # A root folder + the seeded default profile back the series FK columns.
        conn.execute("INSERT INTO root_folders (id, path) VALUES (1, '/lib')")
        profile_id = conn.execute(
            "SELECT id FROM format_profiles LIMIT 1"
        ).fetchone()[0]

        # Legacy-shaped series insert: omit series_group_id AND group_locked.
        conn.execute(
            "INSERT INTO series (cv_volume_id, title, sort_title, matching_key, "
            "status, monitored, monitor_new_items, format_profile_id, "
            "root_folder_id, path, added_at) "
            "VALUES (1, 'Batman (2011)', 'Batman (2011)', 'batman', 'continuing', "
            f"1, 'all', {profile_id}, 1, '/lib/Batman (2011)', "
            "'2026-07-08T00:00:00')"
        )
        row = conn.execute(
            "SELECT series_group_id, group_locked FROM series WHERE cv_volume_id=1"
        ).fetchone()
        assert row == (None, 0)  # NULL group, default-unlocked

        # A grouped series references a real group; ON DELETE SET NULL means
        # deleting the group nulls the link rather than cascading.
        conn.execute(
            "INSERT INTO series_groups (id, title, grouping_key, manual_title, "
            "created_at) VALUES (10, 'Batman', 'batman', 0, '2026-07-08T00:00:00')"
        )
        conn.execute("UPDATE series SET series_group_id = 10 WHERE cv_volume_id = 1")
        conn.execute("DELETE FROM series_groups WHERE id = 10")
        after = conn.execute(
            "SELECT series_group_id FROM series WHERE cv_volume_id = 1"
        ).fetchone()
        assert after == (None,)  # SET NULL, series row survives


@pytest.mark.req("FRG-SER-016")
def test_grouping_key_is_unique(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO series_groups (title, grouping_key, manual_title, created_at) "
            "VALUES ('Batman', 'batman', 0, '2026-07-08T00:00:00')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO series_groups (title, grouping_key, manual_title, "
                "created_at) VALUES ('Batman Dupe', 'batman', 0, "
                "'2026-07-08T00:00:00')"
            )
