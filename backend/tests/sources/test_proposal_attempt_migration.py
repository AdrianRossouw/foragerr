"""``source_entitlements.proposal_attempted_at`` + ``proposal_attempt_error``
(migration 0027): the attempt bookkeeping enrichment orders its work by
(FRG-SRC-013).

Both nullable, additive, forward-only (FRG-DB-002), with NO data rewrite: every
pre-0027 row reads as never-attempted, which puts the existing backlog at the
head of the first post-upgrade run — the honest starting state. (Mirrors the
0026 migration test's shape.)
"""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-SRC-013")
def test_proposal_attempt_columns_are_present_and_nullable(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0027_entitlement_proposal_attempt" in result.applied
    assert current_revision(db_path) == result.head_revision

    with sqlite3.connect(db_path) as conn:
        cols = {
            row[1]: row
            for row in conn.execute("PRAGMA table_info(source_entitlements)")
        }
        assert "proposal_attempted_at" in cols
        assert cols["proposal_attempted_at"][2].upper() == "DATETIME"
        assert cols["proposal_attempted_at"][3] == 0  # NULLABLE — never attempted
        assert cols["proposal_attempted_at"][4] is None  # no invented default

        assert "proposal_attempt_error" in cols
        assert cols["proposal_attempt_error"][2].upper() == "BOOLEAN"
        assert cols["proposal_attempt_error"][3] == 0
        assert cols["proposal_attempt_error"][4] is None


@pytest.mark.req("FRG-SRC-013")
def test_a_legacy_shaped_row_reads_as_never_attempted(tmp_path):
    """The upgrade shape: a row written before the columns existed inserts and
    reads back NULL/NULL — "never attempted", which sorts FIRST in the work
    order, so an existing backlog is exactly what the first post-upgrade run
    picks up."""
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
            "SELECT human_name, proposal_attempted_at, proposal_attempt_error "
            "FROM source_entitlements"
        ).fetchone()

    assert row == ("Legacy Item", None, None)
