"""Guarded pull-entry → library matcher (FRG-PULL-004).

The MATCH phase of a pull refresh: given a week's stored :class:`PullEntryRow`
rows (area A's store) and an open session, decide — for each entry — whether it
maps to a watched library series/issue, and persist that decision as a
``matched_issue_id`` link + a ``match_type`` discriminator via
:func:`foragerr.pull.repo.update_match` (the D4 write path — entries carry a
link + type, *never* a status of their own).

This is deliberately a **thin adapter over the existing library identity
machinery**, not a second matcher:

- Series-name identity reuses the ONE folding implementation
  (:func:`foragerr.parser.normalize.matching_key`, FRG-IMP-005) — the same
  normalization ``series.matching_key`` and the search mapper
  (``search.context.SeriesContext.matches_key``) already use. Discovery is
  **exact normalized-key equality** (name or a registered alias), like the
  search mapper — never a substring match, so "Batman" can never swallow
  "Batman Beyond"; an ambiguous key collision (two watched volumes) is left
  *unmatched* rather than guessed.
- Issue-number identity reuses the shared issue-number parser
  (:func:`foragerr.library.ordering.parse_issue_number`) for a numeric value —
  never a re-parse.

On top of that reuse sit the three hard-won guards the FRG-PULL-004 baseline
keeps from Mylar's ``new_pullcheck`` (the correctness core — this is where wrong
matches are prevented):

1. **ID match** on the source-supplied ComicVine issue id. Those ids are
   *candidates*, not authority (FRG-PULL-002 Notes): a candidate id is trusted
   only after it is verified against library metadata —
   (a) the resolved issue's series must be the series the entry names (a
   ``cv_issue_id`` that "lies" — points at an unrelated series — is rejected),
   and (b) the resolved issue's **book-type** must match the entry's inferred
   book-type (Mylar's book-type guard). A rejected id match falls through to
   the guarded name match.
2. **Guarded NAME match** (``name_seq``), accepted only when ALL hold: the
   normalized series name equals a watched series' name/alias, AND the issue
   number is a plausible next-in-sequence (``0 <= delta < 3`` vs the series'
   latest known issue), AND — when a library issue with that number already
   exists — its date is within **±2 days** of the entry's release date (the
   date-window safety check that reverts wrong-volume collisions).
3. Anything matching neither, or colliding ambiguously, stays **unmatched** —
   never guessed into a link. An unmatched ``#1``/``#0`` whose series is absent
   from the library is additionally tagged **``new_series``** (a *tag* only —
   the backbone never adds a series; that is FRG-PULL-008 in change 2).

A matched-but-missing issue (name/id match to a watched series whose issue
record does not exist locally yet) resolves with ``matched_issue_id=None`` and a
non-``unmatched`` ``match_type`` — area D reads exactly that to enqueue the
``refresh-series`` reconciliation (FRG-PULL-005).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.library.flows import decode_aliases
from foragerr.library.models import IssueRow, SeriesRow
from foragerr.library.ordering import parse_issue_number
from foragerr.parser.normalize import fold, matching_key
from foragerr.parser.result import IssueClassification
from foragerr.parser.vocab import ANNUAL_MARKERS
from foragerr.pull import repo
from foragerr.pull.models import PullEntryRow

#: Guarded name match: issue number must be within this many positions AHEAD of
#: (or equal to) the series' latest known issue — Mylar's ``0 <= delta < 3``
#: next-in-sequence window (`weeklypull.py:1024-1099`).
_MAX_SEQ_DELTA = 3

#: Date-window safety check: a library issue that already carries the entry's
#: number must be dated within this many days of the entry's release date, or
#: the (wrong-volume) collision is rejected — Mylar's pull-week ±2 days revert
#: (`updater.py:583-614`).
_DATE_WINDOW_DAYS = 2

#: Folded annual/special markers → the library ``issue_type`` string they imply.
_BOOKTYPE_MARKERS: dict[str, str] = {
    fold(marker): cls.value for marker, cls in ANNUAL_MARKERS.items()
}
_TOKEN_RE = re.compile(r"[\s\-]+")


@dataclass(frozen=True, slots=True)
class MatchResult:
    """One entry's resolved match (FRG-PULL-004).

    ``match_type`` is one of ``PULL_MATCH_TYPES``. ``matched_issue_id`` is the
    library issue link (``None`` for an unmatched/new-series entry, or for a
    matched-but-missing issue that area D will queue a refresh for).
    ``matched_series_id`` records the watched series an ``id``/``name_seq``
    entry resolved to — area D needs it to enqueue ``refresh-series`` when the
    issue itself does not exist locally yet (FRG-PULL-005); it is ``None`` for
    ``unmatched``/``new_series``.
    """

    entry_id: int
    match_type: str
    matched_issue_id: int | None
    matched_series_id: int | None


# --- library index (the one I/O touch) ---------------------------------------


@dataclass(frozen=True, slots=True)
class _LibIssue:
    issue_id: int
    series_id: int
    value: Fraction | None
    issue_type: str
    date: dt.date | None


@dataclass(frozen=True, slots=True)
class _LibSeries:
    series_id: int
    keys: frozenset[str]
    latest_value: Fraction | None
    #: issue-number value → the library issue carrying it (first wins).
    by_value: dict[Fraction, _LibIssue]


@dataclass(frozen=True, slots=True)
class LibraryMatchIndex:
    """An immutable, in-memory view of the watched library for one match run.

    Built once per week-batch from a single pair of queries, then reused for
    every entry so matching is a cheap in-memory comparison, not an N×M
    re-query — mirroring ``library.matching.build_issue_index``'s posture.
    """

    by_cv_issue: dict[int, _LibIssue]
    series_by_key: dict[str, tuple[_LibSeries, ...]]


async def build_library_index(session: AsyncSession) -> LibraryMatchIndex:
    """Load every watched series + issue into a :class:`LibraryMatchIndex`.

    Only *monitored* series are indexed: the refresh trigger (FRG-PULL-005) acts
    on a "matched watched series", and the weekly projection's library-primary
    half is likewise monitored-scoped, so matching a pull entry to a paused
    series here would enqueue spurious ``refresh-series`` work the rest of the
    pull view never surfaces.
    """
    series_rows = list(
        (
            await session.execute(
                select(SeriesRow).where(SeriesRow.monitored.is_(True))
            )
        )
        .scalars()
        .all()
    )
    issue_rows = list((await session.execute(select(IssueRow))).scalars().all())

    issues_by_series: dict[int, list[_LibIssue]] = {}
    by_cv_issue: dict[int, _LibIssue] = {}
    for issue in issue_rows:
        lib_issue = _LibIssue(
            issue_id=issue.id,
            series_id=issue.series_id,
            value=parse_issue_number(issue.issue_number).value,
            issue_type=issue.issue_type,
            date=issue.store_date or issue.cover_date,
        )
        by_cv_issue[issue.cv_issue_id] = lib_issue
        issues_by_series.setdefault(issue.series_id, []).append(lib_issue)

    series_by_key: dict[str, list[_LibSeries]] = {}
    for series in series_rows:
        lib_issues = issues_by_series.get(series.id, [])
        values = [i.value for i in lib_issues if i.value is not None]
        by_value: dict[Fraction, _LibIssue] = {}
        for lib_issue in lib_issues:
            if lib_issue.value is not None:
                by_value.setdefault(lib_issue.value, lib_issue)
        keys = {series.matching_key}
        # Guard empty keys: an alias (or a name) that folds to "" must not enter
        # the index, or every entry whose name normalizes to empty would collide
        # into a single bucket and false-match. Mirrors search_ops' alias folding.
        keys.update(
            key
            for a in decode_aliases(series.aliases, series_id=series.id)
            if (key := matching_key(a))
        )
        keys.discard("")
        lib_series = _LibSeries(
            series_id=series.id,
            keys=frozenset(keys),
            latest_value=max(values) if values else None,
            by_value=by_value,
        )
        for key in lib_series.keys:
            series_by_key.setdefault(key, []).append(lib_series)

    return LibraryMatchIndex(
        by_cv_issue=by_cv_issue,
        series_by_key={k: tuple(v) for k, v in series_by_key.items()},
    )


# --- pure guards --------------------------------------------------------------


def _entry_book_type(entry: PullEntryRow) -> str:
    """The library ``issue_type`` the entry's own tokens imply (else regular).

    Weekly-pull entries name their annual/special nature in the series title or
    issue-number token (``"Batman Annual"`` / ``"Annual 1"``); a plain numeric
    entry is a regular issue. Reuses the parser's ``ANNUAL_MARKERS`` vocabulary
    so the classification never forks from the filename parser's.
    """
    folded = fold(f"{entry.series_name} {entry.issue_number}")
    tokens = {t for t in _TOKEN_RE.split(folded) if t}
    for marker, issue_type in _BOOKTYPE_MARKERS.items():
        if marker in tokens:
            return issue_type
    return IssueClassification.REGULAR.value


def _series_matches_entry(
    entry: PullEntryRow, index: LibraryMatchIndex
) -> tuple[_LibSeries, ...]:
    """Watched series whose normalized name/alias equals the entry's series."""
    return index.series_by_key.get(matching_key(entry.series_name), ())


def _try_id_match(entry: PullEntryRow, index: LibraryMatchIndex) -> MatchResult | None:
    """ID match on the candidate ``cv_issue_id``, guarded against library data.

    Returns ``None`` (fall through to name match) when there is no candidate id,
    it resolves to no library issue, or a guard rejects it.
    """
    if entry.cv_issue_id is None:
        return None
    lib_issue = index.by_cv_issue.get(entry.cv_issue_id)
    if lib_issue is None:
        return None
    # Guard (a): the candidate id must point at the series the entry names —
    # a lying id (unrelated series) is rejected, not trusted.
    named = {s.series_id for s in _series_matches_entry(entry, index)}
    if lib_issue.series_id not in named:
        return None
    # Guard (b): book-type must agree — an id match to a wrong book-type
    # (e.g. a regular entry whose id resolves to an annual) is rejected.
    if lib_issue.issue_type != _entry_book_type(entry):
        return None
    return MatchResult(
        entry_id=entry.id,
        match_type="id",
        matched_issue_id=lib_issue.issue_id,
        matched_series_id=lib_issue.series_id,
    )


def _try_name_match(entry: PullEntryRow, index: LibraryMatchIndex) -> MatchResult | None:
    """Guarded name match — accepted only if name + sequence + date all hold."""
    candidates = _series_matches_entry(entry, index)
    if len(candidates) != 1:
        return None  # unknown series, or an ambiguous collision → never guess
    series = candidates[0]

    entry_value = parse_issue_number(entry.issue_number).value
    if entry_value is None:
        return None  # non-numeric entry number → cannot sequence-guard

    # Sequence guard: 0 <= delta < 3 vs the series' latest known issue (baseline
    # 0 for a watched-but-empty series, so a plausible #0/#1/#2 start still
    # matches while an out-of-nowhere high number does not).
    baseline = series.latest_value if series.latest_value is not None else Fraction(0)
    delta = entry_value - baseline
    if not (Fraction(0) <= delta < Fraction(_MAX_SEQ_DELTA)):
        return None

    # Date guard: an already-present library issue carrying this number must be
    # dated within ±2 days of the entry — the check that rejects a wrong-volume
    # collision (same name+number, far-off date). No existing issue ⇒ a
    # matched-but-missing future issue (link stays None; area D refreshes).
    existing = series.by_value.get(entry_value)
    if existing is not None and existing.date is not None:
        if abs((existing.date - entry.release_date).days) > _DATE_WINDOW_DAYS:
            return None

    return MatchResult(
        entry_id=entry.id,
        match_type="name_seq",
        matched_issue_id=existing.issue_id if existing is not None else None,
        matched_series_id=series.series_id,
    )


def _is_new_series_number(entry: PullEntryRow) -> bool:
    """Whether the entry is a ``#1``/``#0`` series debut (for new-series tag)."""
    value = parse_issue_number(entry.issue_number).value
    return value in (Fraction(0), Fraction(1))


def match_entry(entry: PullEntryRow, index: LibraryMatchIndex) -> MatchResult:
    """Resolve one entry's match (FRG-PULL-004) — pure over ``index``.

    ID match first (guarded), then the guarded name match, else unmatched —
    with an unmatched ``#1``/``#0`` for a series absent from the library tagged
    ``new_series`` (a tag only; no series is created).
    """
    result = _try_id_match(entry, index) or _try_name_match(entry, index)
    if result is not None:
        return result

    match_type = "unmatched"
    # new-series tag only when the series is genuinely absent (a name collision
    # whose guards failed is NOT a new series — it IS in the library).
    if not _series_matches_entry(entry, index) and _is_new_series_number(entry):
        match_type = "new_series"
    return MatchResult(
        entry_id=entry.id,
        match_type=match_type,
        matched_issue_id=None,
        matched_series_id=None,
    )


# --- batch entry (area D calls this) ------------------------------------------


async def match_week(
    session: AsyncSession,
    entries: Sequence[PullEntryRow],
) -> list[MatchResult]:
    """Match a week's stored entries against the library and persist the result.

    The batch entry area D wires into the ``pull-refresh`` command: builds the
    library index once, resolves every entry through the guards, and writes each
    outcome via :func:`repo.update_match` (link + ``match_type`` ONLY — the D4
    invariant; no status is ever written). Composes into the caller's open
    write transaction — it opens no session and never commits. Returns the
    per-entry results so the trigger step (FRG-PULL-005) can act on a
    matched-but-missing issue without a re-match.
    """
    index = await build_library_index(session)
    results = [match_entry(entry, index) for entry in entries]
    for result in results:
        await repo.update_match(
            session,
            result.entry_id,
            matched_issue_id=result.matched_issue_id,
            match_type=result.match_type,
        )
    return results


__all__ = [
    "LibraryMatchIndex",
    "MatchResult",
    "build_library_index",
    "match_entry",
    "match_week",
]
