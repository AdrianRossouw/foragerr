"""Plausibility annotation for series search candidates (FRG-META-007).

Pure helpers: given the query term and a mapped :class:`SeriesRecord`, produce
the non-binding :class:`Plausibility` signals that ride alongside each search
result. These annotate/rank only — they never auto-pick and (except the
publisher ignore list, applied by the client) never hard-drop a candidate.

Name folding is reused from :func:`foragerr.parser.normalize.matching_key` —
the single shared folding source; no folding is reimplemented here.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from foragerr.metadata.models import Plausibility, SeriesRecord
from foragerr.parser.normalize import matching_key

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def extract_year(term: str) -> int | None:
    """Extract a plausible 4-digit publication year from a query term."""
    match = _YEAR_RE.search(term)
    return int(match.group()) if match else None


def name_similarity(term: str, name: str | None) -> float:
    """0..1 similarity of a candidate name to the query, on the shared
    matching key (article/punctuation/case folding applied identically to
    both sides)."""
    if not name:
        return 0.0
    key_a = matching_key(term)
    key_b = matching_key(name)
    if not key_a or not key_b:
        return 0.0
    return SequenceMatcher(None, key_a, key_b).ratio()


def _target_issue_plausible(
    record: SeriesRecord, target_issue: str | int | None
) -> bool | None:
    """Whether the candidate's issue count can contain ``target_issue``."""
    if target_issue is None:
        return None
    try:
        wanted = int(str(target_issue).split(".")[0])
    except ValueError:
        return None
    if record.count_of_issues is None:
        return None
    return record.count_of_issues >= wanted


def plausibility(
    term: str,
    record: SeriesRecord,
    *,
    target_issue: str | int | None = None,
) -> Plausibility:
    """Compute the plausibility annotations for one candidate."""
    query_year = extract_year(term)
    if query_year is not None and record.start_year is not None:
        year_proximity: int | None = abs(record.start_year - query_year)
    else:
        year_proximity = None
    return Plausibility(
        name_similarity=round(name_similarity(term, record.name), 4),
        year_proximity=year_proximity,
        target_issue_plausible=_target_issue_plausible(record, target_issue),
    )
