"""``source_entitlements.bundle_human_name`` (migration 0026): the order's
bundle display name every review row carries (FRG-SRC-011).

Nullable TEXT, additive, forward-only (FRG-DB-002), and — deliberately — with NO
data rewrite: a pre-0026 row carries NULL until its next sync refreshes it like
any other display detail, and a row whose order names no bundle carries NULL
forever, which is the honest value. (Mirrors the 0025 migration test's shape,
kept in the sources package next to the feature it belongs to.)
"""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-SRC-011")
def test_bundle_human_name_column_is_present_and_nullable(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0026_entitlement_bundle_name" in result.applied
    assert current_revision(db_path) == result.head_revision

    with sqlite3.connect(db_path) as conn:
        cols = {
            row[1]: row
            for row in conn.execute("PRAGMA table_info(source_entitlements)")
        }
        assert "bundle_human_name" in cols
        assert cols["bundle_human_name"][2].upper() == "TEXT"
        assert cols["bundle_human_name"][3] == 0  # NULLABLE — pre-0026 rows
        assert cols["bundle_human_name"][4] is None  # no invented default


@pytest.mark.req("FRG-SRC-011")
def test_a_legacy_shaped_row_round_trips_with_a_null_bundle_name(tmp_path):
    """The upgrade shape: an entitlement written before the column existed still
    inserts and reads back NULL (the "awaiting its next sync" case)."""
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
            "human_name, classification, review_status, formats_json, "
            "created_at, updated_at) VALUES "
            "(1, 'gk', 'mn', 'Legacy Item', 'comic', 'new', '[]', "
            "'2026-07-28 00:00:00', '2026-07-28 00:00:00')"
        )
        row = conn.execute(
            "SELECT human_name, bundle_human_name FROM source_entitlements"
        ).fetchone()

    assert row == ("Legacy Item", None)
