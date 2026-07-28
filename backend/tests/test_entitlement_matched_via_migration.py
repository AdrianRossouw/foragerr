"""``source_entitlements.matched_via`` (migration 0025): the match-provenance
discriminator the import pipeline's ordinal fallback reads (FRG-PP-022 guard 3).

Nullable TEXT, additive, forward-only (FRG-DB-002). A legacy row — matched
before the column existed — carries NULL, which the pipeline deliberately treats
as NOT operator-made (``_auto_accept`` predates this column, so a pre-upgrade
match on an auto-syncing source is indistinguishable from a human one); the
column must therefore accept NULL, not default to a value that would assert a
provenance nothing recorded.
"""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-PP-022")
def test_matched_via_column_is_present_and_nullable(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0025_entitlement_matched_via" in result.applied
    assert current_revision(db_path) == result.head_revision

    with sqlite3.connect(db_path) as conn:
        cols = {
            row[1]: row
            for row in conn.execute("PRAGMA table_info(source_entitlements)")
        }
        assert "matched_via" in cols
        assert cols["matched_via"][2].upper() == "TEXT"
        assert cols["matched_via"][3] == 0  # NULLABLE — legacy rows carry NULL
        assert cols["matched_via"][4] is None  # no default asserting a provenance


@pytest.mark.req("FRG-PP-022")
def test_a_legacy_shaped_row_round_trips_with_a_null_matched_via(tmp_path):
    """The upgrade shape: a matched entitlement written without the column still
    inserts and reads back NULL (the pipeline's "unproven match" case)."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sources (type, name, settings, connection_state, "
            "auto_sync, added_at) VALUES ('humble', 'Humble Bundle', '{}', "
            "'connected', 0, '2026-07-28 00:00:00')"
        )
        conn.execute(
            "INSERT INTO source_entitlements (source_id, gamekey, machine_name, "
            "human_name, classification, review_status, matched_series_id, "
            "formats_json, created_at, updated_at) VALUES "
            "(1, 'gk', 'mn', 'Legacy Item', 'comic', 'matched', 7, '[]', "
            "'2026-07-28 00:00:00', '2026-07-28 00:00:00')"
        )
        row = conn.execute(
            "SELECT matched_series_id, matched_via FROM source_entitlements"
        ).fetchone()

    assert row == (7, None)
