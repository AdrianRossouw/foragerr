"""ORM model + parsed-entry dataclass for the weekly pull store (FRG-PULL-003).

Uses the typed/sentinel-free column conventions from :mod:`foragerr.db.base`
throughout (FRG-DB-008). Two kinds of "entry" exist here, deliberately kept
separate:

- :class:`ParsedPullEntry` — a plain, DB-free dataclass: the typed shape
  FRG-PULL-002's fetch client (``pull/source.py``, area B) parses untrusted
  source JSON into (FRG-NFR-012). It carries no match/identity information —
  matching is a separate phase (area C) that runs against the *stored* row.
- :class:`PullEntryRow` — the persisted row. It carries a nullable
  ``matched_issue_id`` link plus a ``match_type`` discriminator and
  deliberately NO wanted/downloaded/skipped status of its own (D4 invariant,
  FRG-PULL-003 Notes): that state lives on ``IssueRow`` / the download queue
  and is computed by the projection (FRG-PULL-001), never stored here. A
  schema-inventory test in this area asserts no status-shaped column exists
  on this table, mirroring ``library.models``' guard for ``wanted``.

``entry_key()`` is the deterministic per-week identity FRG-PULL-003 requires:
it prefers the source-supplied ComicVine issue id (stable across refreshes
independent of any text drift) and falls back to a normalized
``(series_name, issue_number, publisher)`` tuple — reusing the shared
``matching_key()`` folding (FRG-IMP-005) for the series-name component so this
does not become a second, drifting normalization implementation. This is an
*identity* normalization only; the raw fields stored on the row are untouched
verbatim.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from foragerr.db.base import (
    Base,
    IssueNumberText,
    SentinelFreeText,
    StrictDate,
    StrictDateTime,
    StrictInteger,
)
# `matched_issue_id` below is a cross-package FK (string-resolved at mapper-
# configuration time) to `library.models.IssueRow`'s `issues` table. Import
# the module — not just the name — so that table is registered on the shared
# `Base.metadata` before anything triggers SQLAlchemy's mapper configuration,
# regardless of which module happens to import `foragerr.pull.models` first.
import foragerr.library.models  # noqa: F401
from foragerr.parser.normalize import matching_key

#: Match confidence discriminator persisted on the entry (FRG-PULL-004,
#: decision 4) — never a wanted/downloaded status.
PULL_MATCH_TYPES = ("id", "name_seq", "unmatched", "new_series")

#: Default `match_type` for a freshly fetched/stored entry: the FETCH/STORE
#: phase (`repo.replace_week`) never guesses a match — that is the MATCH
#: phase's (area C) job, run afterward via `repo.update_match`.
UNMATCHED = "unmatched"


@dataclass(frozen=True, slots=True)
class ParsedPullEntry:
    """One source-parsed weekly-pull entry, before storage or matching.

    Plain Python values only — no DB/session dependency — so the fetch
    client (area B) can construct these directly from a byte-capped,
    untrusted-JSON parse (FRG-NFR-012) without importing anything from this
    module beyond the shape itself. `cv_series_id` / `cv_issue_id` are
    source-supplied *candidates* only (FRG-PULL-002 Notes) — they are not
    trusted as match authority; the matcher (area C) still guards them.
    """

    series_name: str
    issue_number: str  # raw source token verbatim; normalized only at match time
    release_date: dt.date
    publisher: str | None = None
    cv_series_id: int | None = None
    cv_issue_id: int | None = None


def entry_key(entry: ParsedPullEntry) -> str:
    """Deterministic per-week entry identity (FRG-PULL-003).

    Prefers `cv_issue_id` (prefixed so it can never collide with the
    name-based fallback's key space); otherwise normalizes
    `(series_name, issue_number, publisher)` — series name through the
    shared `matching_key()` fold (FRG-IMP-005), issue number and publisher
    casefolded/stripped. The same logical source row yields the same key
    across refreshes regardless of incidental whitespace/case drift in the
    source payload.
    """
    if entry.cv_issue_id is not None:
        return f"cv:{entry.cv_issue_id}"
    name_part = matching_key(entry.series_name)
    issue_part = entry.issue_number.strip().casefold()
    publisher_part = (entry.publisher or "").strip().casefold()
    return f"name:{name_part}|{issue_part}|{publisher_part}"


class PullEntryRow(Base):
    """One stored weekly-pull entry (FRG-PULL-003)."""

    __tablename__ = "pull_entries"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    #: ISO year-week key, e.g. "2026-W27" — internally computed from a
    #: store-date, never raw external free text. Plain `Text`, like
    #: `series.matching_key`.
    week: Mapped[str] = mapped_column(Text, nullable=False)
    #: Deterministic per-week identity, see `entry_key()` — internally
    #: derived, plain `Text`.
    entry_key: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str | None] = mapped_column(SentinelFreeText, nullable=True)
    series_name: Mapped[str] = mapped_column(SentinelFreeText, nullable=False)
    #: Raw source token verbatim (FRG-DB-008) — decimals/suffixes round-trip
    #: unmangled, exactly like `issues.issue_number`; normalized only at
    #: match time (area C), never here.
    issue_number: Mapped[str] = mapped_column(IssueNumberText, nullable=False)
    #: Source-supplied ComicVine ids — *candidates* only (FRG-PULL-002/004
    #: Notes), never trusted as match authority.
    cv_series_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    cv_issue_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    release_date: Mapped[dt.date] = mapped_column(StrictDate, nullable=False)
    #: The LINK (D4) — nullable, never a status. `ondelete="SET NULL"`: if the
    #: linked issue is later removed, the historical pull entry survives,
    #: unlinked, rather than disappearing with it.
    matched_issue_id: Mapped[int | None] = mapped_column(
        StrictInteger,
        ForeignKey(
            "issues.id",
            name="fk_pull_entries_matched_issue_id_issues",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    match_type: Mapped[str] = mapped_column(Text, nullable=False, default=UNMATCHED)
    fetched_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("week", "entry_key", name="uq_pull_entries_week_entry_key"),
        CheckConstraint(f"match_type IN {PULL_MATCH_TYPES!r}", name="pull_match_type_valid"),
        Index("ix_pull_entries_week", "week"),
        Index("ix_pull_entries_matched_issue_id", "matched_issue_id"),
    )
