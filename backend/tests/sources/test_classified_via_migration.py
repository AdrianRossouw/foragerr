"""``source_entitlements.classified_via`` (migration 0033) — the provenance the
sync write-back reads to leave an operator-classified row alone (FRG-SRC-016).

Additive, forward-only (FRG-DB-002), with NO data rewrite: a NULL column already
says "the automatic classifier's row", which is what every pre-0033 row was.
"""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-SRC-016")
def test_classified_via_column_is_present_and_nullable(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0033_entitlement_classified_via" in result.applied
    assert current_revision(db_path) == result.head_revision

    with sqlite3.connect(db_path) as conn:
        cols = {
            row[1]: row
            for row in conn.execute("PRAGMA table_info(source_entitlements)")
        }
        assert "classified_via" in cols
        assert cols["classified_via"][2].upper() == "TEXT"
        # NULLABLE with no default: only the operator value is load-bearing, and
        # inventing one for the classifier's own rows would make every row look
        # deliberately classified.
        assert cols["classified_via"][3] == 0
        assert cols["classified_via"][4] is None


@pytest.mark.req("FRG-SRC-016")
def test_a_legacy_shaped_row_reads_as_automatically_classified(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sources (type, name, settings, connection_state, "
            "auto_sync, added_at) VALUES ('humble', 'Example Store', '{}', "
            "'connected', 0, '2026-07-31 00:00:00')"
        )
        conn.execute(
            "INSERT INTO source_entitlements (source_id, gamekey, machine_name, "
            "human_name, classification, review_status, formats_json, "
            "created_at, updated_at) VALUES "
            "(1, 'gk', 'mn', 'Example Item', 'comic', 'new', '[]', "
            "'2026-07-31 00:00:00', '2026-07-31 00:00:00')"
        )
        row = conn.execute(
            "SELECT human_name, classification, classified_via "
            "FROM source_entitlements"
        ).fetchone()

    assert row == ("Example Item", "comic", None)
