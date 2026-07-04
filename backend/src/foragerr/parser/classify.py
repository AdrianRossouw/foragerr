"""Classification of atomic annotation groups and edition/booktype cues
(FRG-IMP-011..013, FRG-IMP-016, FRG-IMP-017).

Scan-group extraction is *structural* (the trailing annotation that is not a
date, count, or recognized edition tag) — no hardcoded ripper list is
consulted for correctness.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from . import grammar
from .normalize import fold
from .result import AnnotationKind, Booktype
from .vocab import ParseOptions


@dataclass(slots=True)
class GroupInfo:
    """Classification outcome for one ``(...)``/``[...]`` group."""

    kind: AnnotationKind
    year: int | None = None
    volume_year: int | None = None
    total: Fraction | None = None
    booktype: Booktype | None = None


def edition_match(folded: str, options: ParseOptions) -> bool:
    """Whole-text match against the edition-tag vocabulary (folded)."""
    return folded in {fold(tag) for tag in options.edition_tags}


def booktype_for(folded: str, options: ParseOptions) -> Booktype | None:
    for cue, booktype in options.booktype_cues:
        if folded == fold(cue):
            return booktype
    return None


def is_page_tag(folded: str) -> bool:
    return bool(grammar.RE_PAGE_PX.match(folded) or grammar.RE_PAGE_CTC.match(folded))


def classify_group(inner: str, reference_year: int, options: ParseOptions) -> GroupInfo:
    """Classify a group's inner text. Pure; never raises."""
    text = inner.strip()
    if not text:
        return GroupInfo(AnnotationKind.GENERIC)
    folded = fold(text)

    # (of N) mini-series count — decimal totals accepted, `(of infinity)` is
    # explicitly not a count marker (FRG-IMP-011).
    m = grammar.RE_OF_COUNT.match(text)
    if m:
        total = grammar.to_fraction(m.group(1))
        if total is not None:
            return GroupInfo(AnnotationKind.COUNT, total=total)
    if folded.startswith("of "):
        return GroupInfo(AnnotationKind.GENERIC)

    # (2 covers)
    if grammar.RE_COVERS.match(text):
        return GroupInfo(AnnotationKind.COVERS)

    # page/quality tags: (36p ctc), (1440px), [1920px]
    if is_page_tag(folded):
        return GroupInfo(AnnotationKind.PAGE_TAG)

    # year-range volume forms: (1953-), (1953-1959) — series start year,
    # not a cover date (FRG-IMP-012). Checked before plain dates.
    m = grammar.RE_YEAR_RANGE.match(text)
    if m and text != m.group(1):  # requires the trailing dash
        start = int(m.group(1))
        if grammar.plausible_year(start, reference_year, lower=1800):
            return GroupInfo(AnnotationKind.YEAR_RANGE, volume_year=start)

    # cover dates: (1987), (June 2019), (2019-05-22) — parenthesized dates
    # accept the 1800s window (18xx reprints, FRG-IMP-013).
    year = grammar.match_date(text, reference_year, lower=1800)
    if year is not None:
        return GroupInfo(AnnotationKind.DATE, year=year)

    # edition/quality vocabulary — may double as a booktype cue
    if edition_match(folded, options):
        return GroupInfo(AnnotationKind.EDITION, booktype=booktype_for(folded, options))
    booktype = booktype_for(folded, options)
    if booktype is not None:
        return GroupInfo(AnnotationKind.EDITION, booktype=booktype)

    return GroupInfo(AnnotationKind.GENERIC)


def scan_group_eligible(inner: str) -> bool:
    """Generic groups qualify as scan groups only with alphabetic content."""
    text = inner.strip()
    return bool(text) and any(ch.isalpha() for ch in text) and not fold(text).startswith("of ")
