"""Format profile entity + default-profile seed (FRG-QUAL-001, FRG-QUAL-002)."""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import select

from foragerr.db.migrations import prepare_database
from foragerr.quality.models import (
    DEFAULT_CUTOFF,
    DEFAULT_FORMATS,
    DEFAULT_PROFILE_NAME,
    FormatProfileRow,
    decode_formats,
    encode_formats,
)


@pytest.mark.req("FRG-QUAL-001")
def test_encode_decode_round_trips_ordered_ladder():
    ladder = ["cbr", "cbz"]
    encoded = encode_formats(ladder)
    assert decode_formats(encoded) == ladder  # order preserved exactly


@pytest.mark.req("FRG-QUAL-001")
async def test_profile_persists_named_ordered_ladder_with_cutoff(db):
    async with db.write_session() as session:
        row = FormatProfileRow(
            name="cbr-then-cbz", formats=encode_formats(["cbr", "cbz"]), cutoff="cbz"
        )
        session.add(row)

    async with db.read_session() as session:
        stored = (
            await session.execute(
                select(FormatProfileRow).where(FormatProfileRow.name == "cbr-then-cbz")
            )
        ).scalar_one()
    assert decode_formats(stored.formats) == ["cbr", "cbz"]  # stable across reads
    assert stored.cutoff == "cbz"


@pytest.mark.req("FRG-QUAL-002")
async def test_first_run_seeds_exactly_one_default_profile_with_the_ladder(db):
    async with db.read_session() as session:
        rows = (
            await session.execute(
                select(FormatProfileRow).where(FormatProfileRow.name == DEFAULT_PROFILE_NAME)
            )
        ).scalars().all()
    assert len(rows) == 1
    (default,) = rows
    assert decode_formats(default.formats) == list(DEFAULT_FORMATS)  # pdf < cbr < cbz
    assert default.cutoff == DEFAULT_CUTOFF


@pytest.mark.req("FRG-QUAL-002")
def test_rerunning_migrations_does_not_duplicate_the_default(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    prepare_database(cfg)  # re-run against an already-migrated database

    with sqlite3.connect(cfg / "foragerr.db") as conn:
        rows = conn.execute(
            "SELECT name, formats, cutoff FROM format_profiles WHERE name = ?",
            (DEFAULT_PROFILE_NAME,),
        ).fetchall()
    assert len(rows) == 1
    assert decode_formats(rows[0][1]) == list(DEFAULT_FORMATS)
    assert rows[0][2] == DEFAULT_CUTOFF
