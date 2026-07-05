"""Tiered Newznab query generation (FRG-IDX-005).

Comics have no id-based query form, so search is ``q=`` text only. The generator
is tiered (Sonarr's structure, id tier left empty): from a cleaned series title
it emits descending-specificity queries — title+issue+year, title+issue+volume,
title+issue (with zero-padding variants 007/07/7), and bare title — each tier
recorded on the results it produces so the comparator can prefer more-specific
matches (lower tier = more specific).

The title is routed through the change-3 sanitizer
(:func:`foragerr.metadata.sanitize.sanitize_cv_text`) before newznab cleaning,
so raw ComicVine text never reaches the wire. Whitespace becomes single spaces
in the ``q`` value; the HTTP factory URL-encodes it on send.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from foragerr.metadata.sanitize import sanitize_cv_text

#: Per-tier result cap and the hard per-fetch cap (~1000) (FRG-IDX-005).
PER_TIER_RESULT_CAP = 200
HARD_RESULT_CAP = 1000

_NON_QUERY_CHARS = re.compile(r"[^0-9a-z ]+", re.IGNORECASE)
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class QuerySpec:
    """One generated query and the tier (0 = most specific) it belongs to."""

    text: str
    tier: int


@dataclass(frozen=True, slots=True)
class SearchTarget:
    """What a search is looking for: a series and (optionally) one issue."""

    series_title: str
    issue_number: str | None = None
    year: int | None = None
    volume: int | None = None


def clean_query_term(text: str) -> str:
    """Clean a title into a Newznab ``q=`` term: sanitize CV text, ``&``→``and``,
    punctuation → spaces, whitespace collapsed (FRG-IDX-005)."""
    cleaned = sanitize_cv_text(text) or ""
    cleaned = cleaned.replace("&", " and ")
    cleaned = _NON_QUERY_CHARS.sub(" ", cleaned)
    return _SPACES.sub(" ", cleaned).strip()


def _issue_variants(issue_number: str) -> list[str]:
    """Zero-padding variants of an issue number (007 / 07 / 7), padded → bare.

    Non-integer issue numbers (``1.5``, ``1.MU``) yield a single verbatim
    variant — padding a decimal/suffix would corrupt it."""
    issue = issue_number.strip()
    if not issue.isdigit():
        return [issue]
    number = int(issue)
    variants = [f"{number:03d}", f"{number:02d}", str(number)]
    seen: set[str] = set()
    ordered: list[str] = []
    for variant in variants:
        if variant not in seen:
            seen.add(variant)
            ordered.append(variant)
    return ordered


def build_queries(target: SearchTarget) -> list[QuerySpec]:
    """Build the descending-specificity query ladder for one target.

    Duplicate query texts collapse to their most-specific (lowest) tier.
    """
    title = clean_query_term(target.series_title)
    if not title:
        return []

    tiers: list[list[str]] = [[] for _ in range(4)]
    issue_variants = (
        _issue_variants(target.issue_number) if target.issue_number else []
    )

    if issue_variants:
        for variant in issue_variants:
            base = f"{title} {variant}"
            if target.year is not None:  # tier 0: title + issue + year
                tiers[0].append(f"{base} {target.year}")
            if target.volume is not None:  # tier 1: title + issue + volume tag
                tiers[1].append(f"{base} v{target.volume}")
            tiers[2].append(base)  # tier 2: title + issue
    tiers[3].append(title)  # tier 3: bare title (broadest)

    specs: list[QuerySpec] = []
    seen: set[str] = set()
    for tier, texts in enumerate(tiers):
        for text in texts:
            if text in seen:
                continue
            seen.add(text)
            specs.append(QuerySpec(text=text, tier=tier))
    return specs
