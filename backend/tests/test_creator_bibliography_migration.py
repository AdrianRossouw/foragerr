"""creator_bibliography cache table + creators.bibliography_fetched_at column
(migration 0018): a new cache table with a CASCADE FK to creators, a unique
(creator_id, cv_volume_id), a creator_id index, plus one additive nullable
DATETIME on ``creators``. Forward-only (FRG-DB-002); no data backfill (``NULL``
stamp = never fetched is correct for every existing creator). FRG-CRTR-005."""

from __future__ import annotations

import sqlite3

import pytest

from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.migrations import current_revision


@pytest.mark.req("FRG-CRTR-005")
def test_creator_bibliography_table_and_stamp_present(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    result = prepare_database(cfg)
    db_path = cfg / DB_FILENAME

    assert "0018_creator_bibliography" in result.applied
    assert current_revision(db_path) == result.head_revision

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")

        # The stamp column exists on creators, nullable, no default.
        creator_cols = {row[1]: row for row in conn.execute("PRAGMA table_info(creators)")}
        assert "bibliography_fetched_at" in creator_cols
        assert creator_cols["bibliography_fetched_at"][3] == 0  # notnull flag off

        # The cache table columns + nullability.
        bib_cols = {row[1]: row for row in conn.execute("PRAGMA table_info(creator_bibliography)")}
        assert bib_cols["cv_volume_id"][3] == 1  # NOT NULL
        assert bib_cols["title"][3] == 1  # NOT NULL
        assert bib_cols["publisher"][3] == 0  # nullable
        assert bib_cols["start_year"][3] == 0  # nullable
        assert bib_cols["count_of_issues"][3] == 0  # nullable

        # The creator_id index exists.
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(creator_bibliography)")}
        assert "ix_creator_bibliography_creator_id" in indexes

        # Seed a creator + two cache rows; the unique (creator_id, cv_volume_id)
        # rejects a duplicate volume for the same creator.
        conn.execute(
            "INSERT INTO creators (id, cv_person_id, name, followed, created_at) "
            "VALUES (1, 100, 'Bill', 0, '2026-07-11T00:00:00')"
        )
        conn.execute(
            "INSERT INTO creator_bibliography (creator_id, cv_volume_id, title) "
            "VALUES (1, 10, 'Fables')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO creator_bibliography (creator_id, cv_volume_id, title) "
                "VALUES (1, 10, 'dup')"
            )

        # Deleting the creator CASCADEs its cache rows.
        conn.execute("DELETE FROM creators WHERE id=1")
        remaining = conn.execute(
            "SELECT COUNT(*) FROM creator_bibliography"
        ).fetchone()[0]
        assert remaining == 0
