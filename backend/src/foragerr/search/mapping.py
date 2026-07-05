"""Release-to-library mapping (FRG-SRCH-003).

Given the parsed structure of a release title, resolve which tracked series it
belongs to (via the shared normalized matching key plus user-editable
per-series aliases) and then which concrete issue. Mapping is exact-key, never
substring, so "Spawn" never captures "Curse of Spawn"; when several volumes
share a key, a year on the release disambiguates.

This is a pure function; it produces a :class:`Mapping` describing what was
resolved. The *rejections* for an unresolved mapping are raised by the
series-match / issue-match specifications, which read this result — keeping the
"what mapped" logic in one place and the "how it is reported" logic in the
specs.
"""

from __future__ import annotations

from dataclasses import dataclass

from foragerr.parser.normalize import matching_key
from foragerr.parser.result import ParseResult

from .context import EvaluationContext, IssueContext, SeriesContext


@dataclass(frozen=True, slots=True)
class Mapping:
    """Outcome of resolving a parsed release against the library.

    - ``series is None``                -> no tracked series matched.
    - ``series`` set, ``issue is None`` -> series matched, issue did not.
    - both set                          -> fully resolved.
    - ``ambiguous`` is True when several same-key volumes matched and no year
      on the release could pick one; treated as unknown-series by the spec.
    """

    series: SeriesContext | None = None
    issue: IssueContext | None = None
    ambiguous: bool = False


NO_MAPPING = Mapping()


def _series_key(parsed: ParseResult) -> str | None:
    """The normalized key to look the series up by, or ``None`` if absent."""
    if parsed.matching_key:
        return parsed.matching_key
    if parsed.series_name:
        return matching_key(parsed.series_name)
    return None


def _disambiguate(
    matches: tuple[SeriesContext, ...], parsed: ParseResult
) -> tuple[SeriesContext | None, bool]:
    """Pick one series from same-key candidates using the release's year.

    Returns ``(series, ambiguous)``. A single match is returned directly. With
    several matches and a year on the release, the volume whose start/volume
    year equals it wins; if none (or several) match the year, the result is
    ambiguous.
    """
    if len(matches) == 1:
        return matches[0], False
    year = parsed.volume_year or parsed.year
    if year is not None:
        by_year = tuple(
            s for s in matches if year in (s.start_year, s.volume_year)
        )
        if len(by_year) == 1:
            return by_year[0], False
    return None, True


def _match_issue(
    series: SeriesContext, parsed: ParseResult
) -> IssueContext | None:
    """Find the concrete issue whose number+suffix equals the parsed issue."""
    if parsed.issue is None or parsed.issue.value is None:
        return None
    want_value = parsed.issue.value
    want_suffix = (parsed.issue.suffix or "").casefold() or None
    for issue in series.issues:
        if issue.number != want_value:
            continue
        have_suffix = (issue.suffix or "").casefold() or None
        if have_suffix == want_suffix:
            return issue
    return None


def map_release(parsed: ParseResult, context: EvaluationContext) -> Mapping:
    """Resolve ``parsed`` to a library series and issue (FRG-SRCH-003)."""
    if not parsed.success:
        return NO_MAPPING
    key = _series_key(parsed)
    if key is None:
        return NO_MAPPING
    matches = context.library.find_by_key(key)
    if not matches:
        return NO_MAPPING
    series, ambiguous = _disambiguate(matches, parsed)
    if series is None:
        return Mapping(series=None, issue=None, ambiguous=ambiguous)
    issue = _match_issue(series, parsed)
    return Mapping(series=series, issue=issue)
