"""``source_entitlements.duplicate_of`` + the ``(source_id, md5)`` index
(migration 0032): the pointer md5 dedupe parks a copy with (FRG-SRC-015).

Additive, nullable, forward-only (FRG-DB-002), with NO data rewrite — every
pre-0032 row reads as unlinked, and the startup backfill (not SQL) applies the
review-state rule that decides which sets may link at all.
"""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-SRC-015")
def test_duplicate_of_column_and_md5_index_are_present(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0032_entitlement_duplicate_of" in result.applied
    assert current_revision(db_path) == result.head_revision

    with sqlite3.connect(db_path) as conn:
        cols = {
            row[1]: row
            for row in conn.execute("PRAGMA table_info(source_entitlements)")
        }
        assert "duplicate_of" in cols
        assert cols["duplicate_of"][2].upper() == "INTEGER"
        assert cols["duplicate_of"][3] == 0  # NULLABLE — most rows are unlinked
        assert cols["duplicate_of"][4] is None  # no invented default

        indexes = {
            row[1]: row
            for row in conn.execute("PRAGMA index_list(source_entitlements)")
        }
        assert "ix_source_entitlements_source_md5" in indexes
        columns = [
            row[2]
            for row in conn.execute(
                "PRAGMA index_info(ix_source_entitlements_source_md5)"
            )
        ]
        assert columns == ["source_id", "md5"]


@pytest.mark.req("FRG-SRC-015")
def test_a_legacy_shaped_row_reads_as_unlinked(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sources (type, name, settings, connection_state, "
            "auto_sync, added_at) VALUES ('humble', 'Example Store', '{}', "
            "'connected', 0, '2026-07-30 00:00:00')"
        )
        conn.execute(
            "INSERT INTO source_entitlements (source_id, gamekey, machine_name, "
            "human_name, classification, review_status, formats_json, "
            "created_at, updated_at) VALUES "
            "(1, 'gk', 'mn', 'Example Item', 'comic', 'new', '[]', "
            "'2026-07-30 00:00:00', '2026-07-30 00:00:00')"
        )
        row = conn.execute(
            "SELECT human_name, review_status, duplicate_of FROM source_entitlements"
        ).fetchone()

    assert row == ("Example Item", "new", None)
