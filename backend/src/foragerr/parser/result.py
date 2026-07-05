"""Structured parse-result types for the comic filename parser (FRG-IMP-003).

One status vocabulary: every parse returns a :class:`ParseResult`. Success is
``failure_reason is None``; failures carry a machine-readable
:class:`FailureReason` plus any salvageable partial fields. Absent fields are
``None`` — never sentinel strings (no ``XCV``/``c11`` placeholders, no
``999999999999999`` magic values).

Confidence is a heuristic in ``[0.0, 1.0]``: the only contract is that
anchored, well-evidenced parses score strictly higher than ambiguous ones
(FRG-IMP-003). Consumers MUST NOT couple to the exact scale — it is an
implementation detail and may be recalibrated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction


class ParseMode(Enum):
    """What kind of name is being parsed (FRG-IMP-001)."""

    FILENAME = "filename"
    FOLDER = "folder"


class Booktype(Enum):
    """Book type from filename cues (FRG-IMP-016). No union members."""

    ISSUE = "issue"
    TPB = "TPB"
    GN = "GN"
    HC = "HC"
    ONE_SHOT = "one-shot"


class IssueClassification(Enum):
    """Issue classification markers (FRG-IMP-015)."""

    REGULAR = "regular"
    ANNUAL = "annual"
    BIANNUAL = "biannual"
    SPECIAL = "special"


class FailureReason(Enum):
    """Machine-readable failure reasons (FRG-IMP-003)."""

    EMPTY_INPUT = "empty-input"
    NO_SERIES_TITLE = "no-series-title"
    INTERNAL_ERROR = "internal-error"


class AnnotationKind(Enum):
    """Classification of annotation tokens/groups (FRG-IMP-017)."""

    DATE = "date"
    YEAR_RANGE = "year-range"
    COUNT = "count"
    COVERS = "covers"
    COVER_VARIANT = "cover-variant"
    PAGE_TAG = "page-tag"
    EDITION = "edition"
    SCAN_GROUP = "scan-group"
    GENERIC = "generic"


@dataclass(frozen=True, slots=True)
class Annotation:
    """A classified annotation with its original (unmangled) text."""

    text: str
    kind: AnnotationKind


@dataclass(frozen=True, slots=True)
class Issue:
    """Structured issue record: (value, suffix, display, classification).

    ``value`` is an exact :class:`~fractions.Fraction` (never float) or
    ``None`` for named/infinity issues. ``suffix`` is the canonical
    vocabulary form (e.g. ``AU``). ``display`` preserves the original
    zero-padded/glyph spelling. ``name`` holds pure-alpha named issues
    (``#Alpha``). ``is_infinity`` is set only for the literal ``∞`` glyph.
    """

    value: Fraction | None
    display: str
    suffix: str | None = None
    classification: IssueClassification = IssueClassification.REGULAR
    is_infinity: bool = False
    name: str | None = None


@dataclass(frozen=True, slots=True)
class IssueRange:
    """Structured issue range (FRG-IMP-010): never silently collapsed."""

    start: Fraction
    end: Fraction
    display: str


@dataclass(frozen=True, slots=True)
class TraceEntry:
    """Per-token classification for the optional token trace."""

    text: str
    role: str


@dataclass(frozen=True, slots=True)
class ParseResult:
    """The single structured result type for every parse (FRG-IMP-003)."""

    series_name: str | None = None
    matching_key: str | None = None
    alt_series: str | None = None
    alt_issue_title: str | None = None
    issue: Issue | None = None
    issue_range: IssueRange | None = None
    miniseries_total: Fraction | None = None
    volume_ordinal: int | None = None
    volume_year: int | None = None
    year: int | None = None
    booktype: Booktype = Booktype.ISSUE
    annotations: tuple[Annotation, ...] = ()
    scan_group: str | None = None
    issue_id: str | None = None
    type: str | None = None
    mode: ParseMode = ParseMode.FILENAME
    confidence: float = 0.0
    failure_reason: FailureReason | None = None
    token_trace: tuple[TraceEntry, ...] | None = field(default=None, compare=False)

    @property
    def success(self) -> bool:
        return self.failure_reason is None

    @property
    def classification(self) -> IssueClassification:
        """Issue classification, REGULAR when no issue is present."""
        if self.issue is not None:
            return self.issue.classification
        return IssueClassification.REGULAR

    def to_dict(self) -> dict:
        """Deterministic, JSON-serializable view (Fractions as strings)."""

        def frac(v: Fraction | None) -> str | None:
            return None if v is None else str(v)

        return {
            "series_name": self.series_name,
            "matching_key": self.matching_key,
            "alt_series": self.alt_series,
            "alt_issue_title": self.alt_issue_title,
            "issue": None
            if self.issue is None
            else {
                "value": frac(self.issue.value),
                "display": self.issue.display,
                "suffix": self.issue.suffix,
                "classification": self.issue.classification.value,
                "is_infinity": self.issue.is_infinity,
                "name": self.issue.name,
            },
            "issue_range": None
            if self.issue_range is None
            else {
                "start": frac(self.issue_range.start),
                "end": frac(self.issue_range.end),
                "display": self.issue_range.display,
            },
            "miniseries_total": frac(self.miniseries_total),
            "volume_ordinal": self.volume_ordinal,
            "volume_year": self.volume_year,
            "year": self.year,
            "booktype": self.booktype.value,
            "annotations": [
                {"text": a.text, "kind": a.kind.value} for a in self.annotations
            ],
            "scan_group": self.scan_group,
            "issue_id": self.issue_id,
            "type": self.type,
            "mode": self.mode.value,
            "confidence": self.confidence,
            "failure_reason": None
            if self.failure_reason is None
            else self.failure_reason.value,
        }

    def to_json(self) -> str:
        """Byte-stable serialization for determinism checks (FRG-IMP-002)."""
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
