"""Evaluation context: everything a specification reads that is not the
candidate itself (FRG-SRCH-001, design decision 7).

The engine is pure and synchronous over in-memory data. The search-command
layer (a later area) resolves the current library, format profile, and search
target from the database and hands them in as the immutable value objects
below. The *dynamic* backing stores that only arrive in change 5 —
download queue, blocklist, free-disk-space — are injected as small
:class:`typing.Protocol` seams with inert defaults here, so change 5 swaps the
real implementations in without touching a single specification.

Nothing in this module imports from ``foragerr.indexers`` or the database — the
engine consumes only :class:`~foragerr.releases.ReleaseCandidate`, the parser,
and these plain value objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Protocol, runtime_checkable

from foragerr.db.base import utcnow
from foragerr.releases import ReleaseCandidate

# --- resolved library view (built by the search-command layer) ---------------


@dataclass(frozen=True, slots=True)
class ExistingFile:
    """A file already on disk for an issue, for the upgrade specification.

    ``format`` is the lowercased container format (``cbz``/``cbr``/``pdf``)
    resolved from the on-disk filename by the search-command layer.
    """

    format: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class IssueContext:
    """One concrete library issue a release can map to (FRG-SRCH-003).

    ``number`` / ``suffix`` are the parsed issue identity (e.g. ``5`` + ``None``
    for ``#5``, ``1`` + ``MU`` for ``1.MU``) so mapping compares like-for-like
    against the parser's output rather than raw strings.
    """

    issue_id: int
    number: Fraction | None
    suffix: str | None = None
    monitored: bool = True
    files: tuple[ExistingFile, ...] = ()


@dataclass(frozen=True, slots=True)
class FormatProfile:
    """A format ladder + cutoff, mirrored from ``FormatProfileRow``.

    ``formats`` is ordered least-preferred first (index = preference rung),
    exactly like ``foragerr.quality`` persists it. ``cutoff`` is the format at
    or above which an issue is considered satisfied.
    """

    formats: tuple[str, ...]
    cutoff: str

    def rung(self, fmt: str | None) -> int:
        """Preference rung of ``fmt`` (higher = better); -1 if unknown."""
        if fmt is None:
            return -1
        try:
            return self.formats.index(fmt.lower())
        except ValueError:
            return -1

    def allows(self, fmt: str | None) -> bool:
        """Whether ``fmt`` is permitted by this profile. Unknown formats are
        permitted here (they cannot be judged before download); import-time
        re-checking is a later area's concern."""
        if fmt is None:
            return True
        return fmt.lower() in self.formats

    @property
    def cutoff_rung(self) -> int:
        return self.rung(self.cutoff)


@dataclass(frozen=True, slots=True)
class SeriesContext:
    """One tracked library series a release can map to (FRG-SRCH-003).

    ``matching_key`` and every entry of ``aliases`` are already normalized via
    the one shared ``foragerr.parser.normalize.matching_key`` folding — mapping
    compares normalized-key equality, never substrings, so "Spawn" never
    swallows "Curse of Spawn".
    """

    series_id: int
    matching_key: str
    profile: FormatProfile
    aliases: tuple[str, ...] = ()
    start_year: int | None = None
    volume_year: int | None = None
    monitored: bool = True
    issues: tuple[IssueContext, ...] = ()

    def matches_key(self, key: str) -> bool:
        return key == self.matching_key or key in self.aliases


@dataclass(frozen=True, slots=True)
class LibrarySnapshot:
    """An immutable view of tracked series for one engine evaluation."""

    series: tuple[SeriesContext, ...] = ()

    def find_by_key(self, key: str) -> tuple[SeriesContext, ...]:
        """Every tracked series whose primary key or an alias equals ``key``.

        More than one can match when two volumes share a normalized title but
        differ by year — the mapper disambiguates by year (FRG-SRCH-003).
        """
        return tuple(s for s in self.series if s.matches_key(key))


@dataclass(frozen=True, slots=True)
class SearchTarget:
    """The series+issue a search was issued for (FRG-SRCH-006).

    Present for search paths (automatic / interactive / backlog); ``None`` for
    a pure mapping evaluation. When present, the search-match specification
    rejects candidates that resolve to any other series or issue.
    """

    series_id: int
    issue_id: int


# --- change-5 dynamic-store seams (inert until change 5) ---------------------


@runtime_checkable
class QueueLookup(Protocol):
    """Is this series+issue already in the download queue? (FRG-SRCH-004)"""

    def is_queued(self, series_id: int, issue_id: int) -> bool: ...


@runtime_checkable
class BlocklistLookup(Protocol):
    """Has this release been blocklisted? (FRG-SRCH-004)"""

    def is_blocklisted(self, candidate: ReleaseCandidate) -> bool: ...


@runtime_checkable
class FreeSpaceLookup(Protocol):
    """Free bytes available for a series' root; ``None`` = unknown/unlimited."""

    def free_bytes(self, series_id: int) -> int | None: ...


class EmptyQueue:
    """Inert queue stub: nothing is ever queued (change 5 replaces this)."""

    def is_queued(self, series_id: int, issue_id: int) -> bool:
        return False


class EmptyBlocklist:
    """Inert blocklist stub: nothing is blocklisted (change 5 replaces this)."""

    def is_blocklisted(self, candidate: ReleaseCandidate) -> bool:
        return False


class UnlimitedSpace:
    """Inert free-space stub: space is never the limiting factor."""

    def free_bytes(self, series_id: int) -> int | None:
        return None


# --- engine configuration ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """Tunables the core specifications read (FRG-SRCH-004).

    Size-bound and preferred-term scoring knobs (FRG-QUAL-003/004) are M2 and
    deliberately absent here.
    """

    #: Usenet retention: candidates older than this are permanently rejected.
    #: ``None`` disables the check (FRG-IDX-009 / FRG-SRCH-004).
    retention_days: int | None = None
    #: Minimum release age in minutes; younger candidates are *temporarily*
    #: rejected so they can pass on a later run (FRG-SRCH-004).
    min_age_minutes: int = 0
    #: Terms that MUST all appear in the release title (case-insensitive).
    must_contain: tuple[str, ...] = ()
    #: Terms that must NOT appear — Mylar's IGNORE_SEARCH_WORDS (FRG-SRCH-004).
    must_not_contain: tuple[str, ...] = ()
    #: Whether upgrades over an existing file are permitted at all.
    upgrades_allowed: bool = True


DEFAULT_CONFIG = EngineConfig()


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    """Everything a specification reads besides the candidate (FRG-SRCH-001)."""

    library: LibrarySnapshot = field(default_factory=LibrarySnapshot)
    target: SearchTarget | None = None
    config: EngineConfig = DEFAULT_CONFIG
    now: datetime = field(default_factory=utcnow)
    queue: QueueLookup = field(default_factory=EmptyQueue)
    blocklist: BlocklistLookup = field(default_factory=EmptyBlocklist)
    free_space: FreeSpaceLookup = field(default_factory=UnlimitedSpace)

    @property
    def reference_year(self) -> int:
        """Year handed to the parser for year-vs-issue disambiguation."""
        return self.now.year
