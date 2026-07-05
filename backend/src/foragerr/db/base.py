"""Declarative base and typed, sentinel-free column conventions (FRG-DB-008).

Design (m1-foundation, decision 2): all columns are typed; missing values are
SQL NULL, never sentinel strings ('None', '0000', '0000-00-00'). SQLite's
flexible typing would happily store a string in an INTEGER column, so the
strict types below reject mistyped binds at the persistence layer, and the
sentinel-aware text type normalizes known sentinel strings to NULL. Issue
numbers are stored as TEXT preserving decimals and suffixes ('1.5', '1.MU')
with no numeric coercion.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Date, DateTime, Integer, MetaData, Text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

#: Sentinel strings that legacy trackers persist in place of NULL — never
#: stored by foragerr (FRG-DB-008).
SENTINEL_STRINGS = frozenset({"None", "none", "NULL", "null", "0000", "0000-00-00"})

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> dt.datetime:
    """Naive UTC now — all persisted timestamps are naive UTC."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Project declarative base carrying the naming convention."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class SentinelFreeText(TypeDecorator):
    """TEXT column that normalizes sentinel strings to SQL NULL."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(
                f"text column requires str or None, got {type(value).__name__}: {value!r}"
            )
        if value.strip() in SENTINEL_STRINGS:
            return None  # normalize, never persist a sentinel (FRG-DB-008)
        return value


class IssueNumberText(TypeDecorator):
    """Issue numbers as TEXT, preserving decimals and suffixes verbatim.

    Rejects non-string binds so '1.5' can never be coerced through a float
    and '1.MU' can never be truncated (FRG-DB-008).
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(
                "issue numbers are stored as TEXT; pass a string "
                f"(got {type(value).__name__}: {value!r})"
            )
        return value


class StrictDateTime(TypeDecorator):
    """DATETIME column rejecting strings (incl. sentinels like '0000-00-00').

    Accepts naive datetimes as UTC; aware datetimes are converted to naive UTC.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> dt.datetime | None:
        if value is None:
            return None
        if not isinstance(value, dt.datetime):
            raise TypeError(
                f"datetime column requires datetime or None, got "
                f"{type(value).__name__}: {value!r}"
            )
        if value.tzinfo is not None:
            value = value.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return value


class StrictDate(TypeDecorator):
    """DATE column rejecting strings and datetimes — date objects only."""

    impl = Date
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> dt.date | None:
        if value is None:
            return None
        if isinstance(value, dt.datetime) or not isinstance(value, dt.date):
            raise TypeError(
                f"date column requires date or None, got "
                f"{type(value).__name__}: {value!r}"
            )
        return value


class StrictInteger(TypeDecorator):
    """INTEGER column rejecting strings/floats/bools — real ints only."""

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(
                f"integer column requires int or None, got "
                f"{type(value).__name__}: {value!r}"
            )
        return value
