"""keystore_meta single-row table (migration 0020): a new table with salt (BLOB),
sentinel (TEXT), created_at (DATETIME), all NOT NULL. Provisioned empty — the
id=1 row is written at first keyed boot by init_keystore, not by the migration.
Forward-only (FRG-DB-002). FRG-AUTH-008."""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-AUTH-008")
def test_keystore_meta_table_present_and_empty(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0020_keystore_meta" in result.applied
    assert current_revision(db_path) == result.head_revision

    with sqlite3.connect(db_path) as conn:
        cols = {row[1]: row for row in conn.execute("PRAGMA table_info(keystore_meta)")}
        assert set(cols) == {"id", "salt", "sentinel", "created_at"}
        assert cols["salt"][3] == 1  # NOT NULL
        assert cols["sentinel"][3] == 1  # NOT NULL
        assert cols["created_at"][3] == 1  # NOT NULL
        # Provisioned empty: the keystore row is written at first keyed boot.
        assert conn.execute("SELECT COUNT(*) FROM keystore_meta").fetchone()[0] == 0
