"""Typed, sentinel-free schema conventions (FRG-DB-008)."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from foragerr.db import (
    Database,
    IssueNumberText,
    SentinelFreeText,
    SENTINEL_STRINGS,
    StrictDate,
    StrictDateTime,
    StrictInteger,
)


class _ConventionBase(DeclarativeBase):
    pass


class Issue(_ConventionBase):
    """Throwaway model exercising every column convention."""

    __tablename__ = "convention_issues"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    issue_number: Mapped[str | None] = mapped_column(IssueNumberText, nullable=True)
    comicvine_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    publication_date: Mapped[dt.date | None] = mapped_column(StrictDate, nullable=True)
    added_at: Mapped[dt.datetime | None] = mapped_column(StrictDateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(SentinelFreeText, nullable=True)


@pytest.fixture
async def issue_db(migrated_dir):
    database = Database(db_path=migrated_dir / "foragerr.db")
    async with database.engine.begin() as conn:
        await conn.run_sync(_ConventionBase.metadata.create_all)
    yield database
    await database.close()


async def _sentinel_scan(database: Database) -> list[tuple]:
    """Data-quality query: any sentinel string in the scanned columns?"""
    sentinels = ",".join(f"'{s}'" for s in SENTINEL_STRINGS)
    async with database.read_session() as session:
        result = await session.execute(
            text(
                "SELECT id FROM convention_issues WHERE "
                f"CAST(comicvine_id AS TEXT) IN ({sentinels}) "
                f"OR CAST(publication_date AS TEXT) IN ({sentinels}) "
                f"OR CAST(added_at AS TEXT) IN ({sentinels}) "
                f"OR note IN ({sentinels})"
            )
        )
        return result.fetchall()


@pytest.mark.req("FRG-DB-008")
async def test_missing_values_round_trip_as_sql_null(issue_db):
    async with issue_db.write_session() as session:
        session.add(Issue(issue_number="1"))  # every optional field absent

    async with issue_db.read_session() as session:
        issue = (await session.execute(select(Issue))).scalars().one()
        assert issue.comicvine_id is None
        assert issue.publication_date is None
        assert issue.added_at is None
        assert issue.note is None
        raw = (
            await session.execute(
                text("SELECT comicvine_id, publication_date, added_at, note "
                     "FROM convention_issues")
            )
        ).one()
    assert all(value is None for value in raw)  # SQL NULL, not 'None'/'0000'
    assert await _sentinel_scan(issue_db) == []


@pytest.mark.req("FRG-DB-008")
async def test_sentinel_strings_are_rejected_or_normalized(issue_db):
    # Text column: sentinel is normalized to NULL.
    async with issue_db.write_session() as session:
        session.add(Issue(issue_number="2", note="None"))
    async with issue_db.read_session() as session:
        issue = (await session.execute(select(Issue))).scalars().one()
        assert issue.note is None

    # Date column: the sentinel string is rejected outright.
    with pytest.raises(StatementError):
        async with issue_db.write_session() as session:
            session.add(Issue(issue_number="3", publication_date="0000-00-00"))

    # Id column: a stringly 'None' is rejected outright.
    with pytest.raises(StatementError):
        async with issue_db.write_session() as session:
            session.add(Issue(issue_number="4", comicvine_id="None"))

    assert await _sentinel_scan(issue_db) == []  # zero sentinel rows persisted


@pytest.mark.req("FRG-DB-008")
async def test_issue_numbers_preserve_decimals_and_suffixes(issue_db):
    numbers = ["1", "1.5", "1.MU"]
    async with issue_db.write_session() as session:
        for number in numbers:
            session.add(Issue(issue_number=number))

    async with issue_db.read_session() as session:
        stored = [
            row[0]
            for row in await session.execute(
                text("SELECT issue_number FROM convention_issues ORDER BY id")
            )
        ]
    assert stored == numbers  # exact TEXT round-trip, no coercion

    # Numeric binds are refused — '1.5' must never arrive via a float.
    with pytest.raises(StatementError):
        async with issue_db.write_session() as session:
            session.add(Issue(issue_number=1.5))


@pytest.mark.req("FRG-DB-008")
async def test_typed_columns_reject_mistyped_values(issue_db):
    # Non-date string into a datetime column.
    with pytest.raises(StatementError):
        async with issue_db.write_session() as session:
            session.add(Issue(issue_number="5", added_at="last tuesday"))

    # Float into an integer id column.
    with pytest.raises(StatementError):
        async with issue_db.write_session() as session:
            session.add(Issue(issue_number="6", comicvine_id=12.7))

    # Datetime into a date column.
    with pytest.raises(StatementError):
        async with issue_db.write_session() as session:
            session.add(Issue(issue_number="7", publication_date=dt.datetime(2026, 1, 1)))

    async with issue_db.read_session() as session:
        rows = (await session.execute(select(Issue))).scalars().all()
    assert rows == []  # nothing stringly-typed was stored
