"""Format profile entity and default-profile seed (FRG-QUAL-001, FRG-QUAL-002).

A format profile is a named, ordered ladder of allowed comic container
formats (least to most preferred) plus a cutoff format at or above which an
issue is considered satisfied. ``formats`` is persisted as canonical JSON
(a plain list of lowercase format strings in preference order) — there is no
``Strict*`` JSON type in :mod:`foragerr.db.base`, so this uses plain
``Text`` exactly like the command backbone's ``payload`` column: it is
internally-generated structured data, not free-form external text, so the
sentinel-normalizing ``SentinelFreeText`` type is deliberately not used here
(a profile ladder can never legitimately contain a sentinel string).

Design note (deviation from the terse decision-1 column list): decision 1
lists this table as ``(id, name UNIQUE, formats JSON ordered list,
cutoff)`` with no "is default" flag, yet FRG-QUAL-002's scenarios require
the seeded profile to be identifiable as "the default". Rather than add an
``is_default`` boolean column (which the design decision doesn't mention),
the default profile is identified by a reserved, well-known name
(:data:`DEFAULT_PROFILE_NAME`). Downstream add-flow code (change 3, not in
this package) should look up the default by that name. This keeps the
schema exactly as decision 1 specifies while still satisfying "marked as
the default" — flagged here for the orchestrator/flows-agent.
"""

from __future__ import annotations

import json

from sqlalchemy import Connection, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from foragerr.db.base import Base, StrictInteger

#: The M1 comic container format ladder (FRG-QUAL-001/002). Order matters:
#: index position is preference rank, least to most preferred.
DEFAULT_FORMATS: tuple[str, ...] = ("pdf", "cbr", "cbz")
DEFAULT_CUTOFF = "cbz"

#: Reserved name of the seeded default profile — see module docstring.
DEFAULT_PROFILE_NAME = "Default"


class FormatProfileRow(Base):
    """A named, ordered format ladder with a cutoff (FRG-QUAL-001)."""

    __tablename__ = "format_profiles"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    #: Canonical JSON array of lowercase format strings, least to most
    #: preferred, e.g. '["pdf","cbr","cbz"]'. Use :func:`encode_formats` /
    #: :func:`decode_formats` rather than hand-rolling json calls.
    formats: Mapped[str] = mapped_column(Text, nullable=False)
    cutoff: Mapped[str] = mapped_column(Text, nullable=False)


def encode_formats(formats: list[str] | tuple[str, ...]) -> str:
    """Canonical JSON encoding of an ordered format ladder."""
    return json.dumps(list(formats), separators=(",", ":"))


def decode_formats(raw: str) -> list[str]:
    """Decode a persisted format ladder back into an ordered list."""
    return list(json.loads(raw))


def seed_default_format_profile(connection: Connection) -> None:
    """Idempotently insert the seeded default profile (FRG-QUAL-002).

    Safe to call repeatedly (migration re-runs, or any other startup path):
    the single ``INSERT ... WHERE NOT EXISTS`` statement is itself the
    idempotency guard, so the default is created exactly once and never
    duplicated even under concurrent callers. Uses a raw connection (not an
    ORM session) so it works identically from inside an Alembic
    ``upgrade()``.
    """
    connection.execute(
        text(
            "INSERT INTO format_profiles (name, formats, cutoff) "
            "SELECT :name, :formats, :cutoff "
            "WHERE NOT EXISTS (SELECT 1 FROM format_profiles WHERE name = :name)"
        ),
        {
            "name": DEFAULT_PROFILE_NAME,
            "formats": encode_formats(DEFAULT_FORMATS),
            "cutoff": DEFAULT_CUTOFF,
        },
    )
