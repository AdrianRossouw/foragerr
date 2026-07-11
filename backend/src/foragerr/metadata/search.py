"""Plausibility annotation for series search candidates (FRG-META-007).

Pure helpers: given the query term and a mapped :class:`SeriesRecord`, produce
the non-binding :class:`Plausibility` signals that ride alongside each search
result. These annotate/rank only — they never auto-pick and (except the
publisher ignore list, applied by the client) never hard-drop a candidate.

Name folding is reused from :func:`foragerr.parser.normalize.matching_key` —
the single shared folding source; no folding is reimplemented here.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from difflib import SequenceMatcher
from typing import TypeVar

from foragerr.metadata.models import Plausibility, SeriesRecord
from foragerr.parser.normalize import matching_key

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

_T = TypeVar("_T")

#: Year-distance stand-in for a candidate that offers no comparable year — the
#: term carried a year but this candidate has no start year, or the term carried
#: no year at all. Infinity sorts such a candidate AFTER any candidate with a
#: real year distance at equal name similarity, and — because every no-year
#: candidate shares it — leaves them in upstream order relative to each other.
_NO_YEAR_DISTANCE = math.inf


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


def sort_by_relevance(
    term: str,
    items: Sequence[_T],
    *,
    record_of: Callable[[_T], SeriesRecord],
) -> list[_T]:
    """Order series-search candidates by relevance, server-side (FRG-META-015).

    Applied AFTER annotation, on the assembled candidate list, and shared
    verbatim by the full lookup and the bounded suggest endpoint so the two can
    never drift (the FRG-META-015 parity guarantee). Ordering is presentation
    only: it drops nothing, selects nothing, and preserves every candidate.

    Sort key per candidate (ascending Python tuple sort)::

        (-name_similarity, year_distance, upstream_index)

    * ``name_similarity`` — 0..1 similarity of the candidate name to ``term`` on
      the shared matching key; negated so the closest title ranks first.
    * ``year_distance`` — ``abs(start_year - query_year)`` when ``term`` carries
      a 4-digit year AND the candidate has a start year, else ``+inf``. So at
      equal name similarity a closer year wins, and a candidate with no
      comparable year sorts AFTER those that have one. When the term carries no
      year every candidate gets ``+inf`` and this term drops out, leaving the
      upstream tiebreak in charge.
    * ``upstream_index`` — the candidate's position in ComicVine's returned
      (``name:asc``) order, making the sort TOTAL and STABLE: equal-signal
      candidates keep CV's order, so pagination/caps behave unchanged.

    ``record_of`` extracts the :class:`SeriesRecord` from each item, so both the
    plausibility-annotated :class:`SeriesCandidate` (lookup) and the bare
    :class:`SeriesRecord` (suggest) share one implementation. The signals are
    recomputed from ``term`` + the record identically on both paths — not read
    from a precomputed (and, for lookup, rounded) field — so the two endpoints
    order the candidates they share byte-identically.
    """
    query_year = extract_year(term)

    def _key(indexed: tuple[int, _T]) -> tuple[float, float, int]:
        upstream_index, item = indexed
        record = record_of(item)
        similarity = name_similarity(term, record.name)
        if query_year is not None and record.start_year is not None:
            year_distance: float = float(abs(record.start_year - query_year))
        else:
            year_distance = _NO_YEAR_DISTANCE
        return (-similarity, year_distance, upstream_index)

    return [item for _, item in sorted(enumerate(items), key=_key)]


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
