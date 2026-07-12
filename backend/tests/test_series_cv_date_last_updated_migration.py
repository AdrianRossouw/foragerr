"""series.cv_date_last_updated bookkeeping column (migration 0019): one additive
nullable TEXT column on ``series``. Stores the ComicVine volume ``date_last_updated``
from the last COMPLETE issue walk, compared by equality only for the
unchanged-volume refresh short-circuit (FRG-META-017). Forward-only (FRG-DB-002);
no data backfill (``NULL`` = no complete walk recorded yet, forcing a full walk).
"""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-META-017")
def test_cv_date_last_updated_column_present_nullable_text(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0019_series_cv_date_last_updated" in result.applied
    assert current_revision(db_path) == result.head_revision

    with sqlite3.connect(db_path) as conn:
        cols = {row[1]: row for row in conn.execute("PRAGMA table_info(series)")}
        assert "cv_date_last_updated" in cols
        # Nullable (no NOT NULL) and TEXT affinity — an opaque upstream token.
        assert cols["cv_date_last_updated"][3] == 0  # notnull flag off
        assert cols["cv_date_last_updated"][2].upper() in ("TEXT", "")

        # Existing rows are legal with the column left NULL (no backfill needed).
        conn.execute("INSERT INTO root_folders (id, path) VALUES (1, '/lib')")
        profile_id = conn.execute("SELECT id FROM format_profiles LIMIT 1").fetchone()[0]
        conn.execute(
            "INSERT INTO series (id, cv_volume_id, title, sort_title, matching_key, "
            "status, monitored, monitor_new_items, format_profile_id, root_folder_id, "
            "path, added_at) VALUES (1, 10, 's', 's', 's', 'continuing', 1, 'all', "
            f"{profile_id}, 1, '/lib/s', '2026-07-12T00:00:00')"
        )
        row = conn.execute(
            "SELECT cv_date_last_updated FROM series WHERE id=1"
        ).fetchone()
        assert row == (None,)
