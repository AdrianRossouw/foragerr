"""Metadata-derived weekly pull projection (FRG-PULL-001) + its API row shape
merge (FRG-API-019) — area E of m3-pull-backbone.

Two data sources feed one merged view, deliberately kept in separate halves
so the *library* half never depends on the *pull* half being populated:

- **Library-primary** (FRG-PULL-001): the watched-series issues store-dated
  in the target week, each annotated with derived state computed from issue
  + queue records (FRG-SER-004 / FRG-DL-008). This half never touches
  ``pull_entries`` — it works identically whether the pull source has never
  been configured, is currently degraded, or has never run at all.
- **Stored pull entries** (FRG-PULL-003, read via :mod:`foragerr.pull.repo`):
  when present, a stored entry ENRICHES the library-primary row for the
  issue it links to (contributing the source's own publisher / ComicVine
  candidate ids / ``match_type``) and contributes rows the library alone
  cannot: unmatched / new-series entries (no issue exists to derive state
  from) and matched-but-not-yet-created entries (the matcher, area C,
  recognised the series but ``refresh-series`` has not created the local
  issue yet, FRG-PULL-005) — surfaced as ``state = "pending_refresh"``.

Nothing here ever reads or writes a wanted/downloaded status onto a pull
entry (D4, FRG-PULL-003 Notes) — ``state`` is computed at request time from
``IssueRow`` / ``IssueFileRow`` / ``TrackedDownloadRow`` and is never stored.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.downloads.models import TrackedDownloadRow
from foragerr.downloads.state import TrackedDownloadState
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow
from foragerr.pull import repo
from foragerr.pull.models import PullEntryRow

__all__ = [
    "STATE_DOWNLOADED",
    "STATE_DOWNLOADING",
    "STATE_MISSING_WANTED",
    "STATE_PENDING_REFRESH",
    "STATE_UNMONITORED",
    "MalformedWeek",
    "ProjectedPullEntry",
    "current_week",
    "week_date_range",
    "weekly_pull",
]

#: Derived-state vocabulary (FRG-PULL-001 / FRG-API-019). Values are plain
#: lowercase snake_case strings, mirroring `match_type`'s convention
#: (`pull/models.py`) — never a status stored anywhere (D4).
STATE_MISSING_WANTED = "missing_wanted"
STATE_DOWNLOADING = "downloading"
STATE_DOWNLOADED = "downloaded"
STATE_UNMONITORED = "unmonitored"
#: A pull entry the matcher (area C) linked to a watched series/issue-number
#: by id or guarded name match, but whose local issue row does not exist yet
#: (`matched_issue_id IS NULL` — FRG-PULL-005: `refresh-series` will create
#: it and the entry is backfilled on a later refresh, design decision 5/6).
STATE_PENDING_REFRESH = "pending_refresh"

#: Tracked-download states counted as "actively downloading" for the
#: projection. FAILED / FAILED_PENDING / IGNORED are deliberately excluded —
#: like `library.repo.wanted_issues()`, a failed grab does not block an
#: issue's missing/wanted derivation; it stays retryable.
_ACTIVE_DOWNLOAD_STATES = frozenset(
    {
        TrackedDownloadState.DOWNLOADING.value,
        TrackedDownloadState.IMPORT_PENDING.value,
        TrackedDownloadState.IMPORT_BLOCKED.value,
        TrackedDownloadState.IMPORTING.value,
    }
)

_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")


class MalformedWeek(ValueError):
    """Raised when a ``week`` value is not a valid ISO year-week key.

    Covers both a value not shaped like ``"YYYY-Www"`` and one naming a week
    number that does not exist for that ISO year (e.g. week 53 in a year with
    only 52 ISO weeks) — ``date.fromisocalendar`` rejects the latter.
    """


def current_week(as_of: dt.date | None = None) -> str:
    """The ISO year-week key (e.g. ``"2026-W27"``) for ``as_of`` (default:
    today). Uses ``date.isocalendar()`` so a year-boundary date (e.g. 31
    December landing in ISO week 1 of the following year) resolves to the
    correct ISO year, not the calendar year."""
    as_of = as_of or dt.date.today()
    iso_year, iso_week, _ = as_of.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def week_date_range(week: str) -> tuple[dt.date, dt.date]:
    """The inclusive ``[monday, sunday]`` store-date range for an ISO
    year-week key. Raises :class:`MalformedWeek` — never a bare
    :class:`ValueError` a caller might mistake for something else — on any
    malformed or out-of-range value."""
    match = _WEEK_RE.match(week)
    if not match:
        raise MalformedWeek(
            f"malformed week {week!r}; expected an ISO year-week like '2026-W27'"
        )
    year, week_num = int(match.group(1)), int(match.group(2))
    try:
        monday = dt.date.fromisocalendar(year, week_num, 1)
    except ValueError as exc:
        raise MalformedWeek(f"malformed week {week!r}: {exc}") from exc
    return monday, monday + dt.timedelta(days=6)


@dataclass(frozen=True, slots=True)
class ProjectedPullEntry:
    """One row of the merged weekly projection — the shape
    :mod:`foragerr.api.pull` turns into the wire resource.

    ``pull_entry_id`` is ``None`` for a pure library-primary row with no
    corresponding stored pull entry (no pull source configured/degraded, or
    the source simply hasn't surfaced this release) — there is no physical
    ``pull_entries`` row backing it. ``state`` is ``None`` only for an
    unmatched / new-series pull entry, which links to no issue at all.
    """

    pull_entry_id: int | None
    week: str
    publisher: str | None
    series_name: str
    issue_number: str | None
    release_date: dt.date | None
    cv_series_id: int | None
    cv_issue_id: int | None
    match_type: str | None
    matched_issue_id: int | None
    series_id: int | None
    state: str | None


def _derive_issue_state(
    *,
    series_monitored: bool,
    issue_monitored: bool,
    has_file: bool,
    tracked_state: str | None,
) -> str:
    if not (series_monitored and issue_monitored):
        return STATE_UNMONITORED
    if has_file:
        return STATE_DOWNLOADED
    if tracked_state in _ACTIVE_DOWNLOAD_STATES:
        return STATE_DOWNLOADING
    return STATE_MISSING_WANTED


async def _tracked_state_by_issue(
    session: AsyncSession, issue_ids: set[int]
) -> dict[int, str]:
    """The most relevant `tracked_downloads.state` per issue id.

    An issue can accumulate more than one historical tracked-download row
    (a failed grab re-searched and re-grabbed) — an ACTIVE state always wins
    over a terminal one so a stale failed row can never mask a fresh grab.
    """
    if not issue_ids:
        return {}
    rows = (
        await session.execute(
            select(TrackedDownloadRow.issue_id, TrackedDownloadRow.state).where(
                TrackedDownloadRow.issue_id.in_(issue_ids)
            )
        )
    ).all()
    by_issue: dict[int, str] = {}
    for issue_id, state in rows:
        if issue_id is None:
            continue
        if issue_id not in by_issue or state in _ACTIVE_DOWNLOAD_STATES:
            by_issue[issue_id] = state
    return by_issue


async def _issue_ids_with_file(session: AsyncSession, issue_ids: set[int]) -> set[int]:
    if not issue_ids:
        return set()
    rows = (
        await session.execute(
            select(IssueFileRow.issue_id)
            .where(IssueFileRow.issue_id.in_(issue_ids))
            .distinct()
        )
    ).scalars().all()
    return set(rows)


async def _entries_for_issue_ids(
    session: AsyncSession, week: str, issue_ids: set[int]
) -> dict[int, ProjectedPullEntry]:
    """Batch-build library-sourced projected entries for exactly these issue
    ids (used both for the week-range query and for a matched pull entry
    whose linked issue's own store_date happens to sit outside the range)."""
    if not issue_ids:
        return {}
    rows = (
        await session.execute(
            select(IssueRow, SeriesRow)
            .join(SeriesRow, SeriesRow.id == IssueRow.series_id)
            .where(IssueRow.id.in_(issue_ids))
        )
    ).all()
    tracked_by_issue = await _tracked_state_by_issue(session, issue_ids)
    has_file_ids = await _issue_ids_with_file(session, issue_ids)

    entries: dict[int, ProjectedPullEntry] = {}
    for issue, series in rows:
        entries[issue.id] = ProjectedPullEntry(
            pull_entry_id=None,
            week=week,
            publisher=series.publisher,
            series_name=series.title,
            issue_number=issue.issue_number,
            release_date=issue.store_date,
            cv_series_id=series.cv_volume_id,
            cv_issue_id=issue.cv_issue_id,
            match_type=None,
            matched_issue_id=issue.id,
            series_id=series.id,
            state=_derive_issue_state(
                series_monitored=series.monitored,
                issue_monitored=issue.monitored,
                has_file=issue.id in has_file_ids,
                tracked_state=tracked_by_issue.get(issue.id),
            ),
        )
    return entries


async def _library_primary_entries(
    session: AsyncSession, week: str, start: dt.date, end: dt.date
) -> dict[int, ProjectedPullEntry]:
    """Watched-series issues store-dated in ``[start, end]`` (FRG-PULL-001).

    Keyed by issue id. Never touches ``pull_entries`` — this is the half
    that keeps the projection "fully functional when no pull source is
    configured or the source is degraded" (FRG-PULL-001)."""
    ids = (
        await session.execute(
            select(IssueRow.id)
            .join(SeriesRow, SeriesRow.id == IssueRow.series_id)
            .where(SeriesRow.monitored.is_(True))
            .where(IssueRow.store_date.is_not(None))
            .where(IssueRow.store_date >= start)
            .where(IssueRow.store_date <= end)
        )
    ).scalars().all()
    return await _entries_for_issue_ids(session, week, set(ids))


def _pending_refresh(row: PullEntryRow) -> bool:
    """A matcher-confident entry (area C: ``id``/``name_seq``) whose local
    issue does not exist yet — FRG-PULL-005's "matched but missing" case."""
    return row.match_type in ("id", "name_seq") and row.matched_issue_id is None


async def weekly_pull(session: AsyncSession, week: str) -> list[ProjectedPullEntry]:
    """The full FRG-API-019 projection for ``week``: library-primary
    (FRG-PULL-001) merged with any stored pull entries (FRG-PULL-003).

    Raises :class:`MalformedWeek` for an invalid ``week``. Never raises for
    an empty/unconfigured/degraded pull source — the library-primary half
    alone still yields a (possibly empty) result.
    """
    start, end = week_date_range(week)
    by_issue = await _library_primary_entries(session, week, start, end)

    stored = await repo.list_week(session, week)
    extra: list[ProjectedPullEntry] = []
    if stored:
        linked_ids = {r.matched_issue_id for r in stored if r.matched_issue_id is not None}
        missing_ids = linked_ids - by_issue.keys()
        if missing_ids:
            by_issue.update(await _entries_for_issue_ids(session, week, missing_ids))

        for row in stored:
            if row.matched_issue_id is not None:
                base = by_issue.get(row.matched_issue_id)
                if base is None:
                    # The linked issue was deleted after this entry was
                    # matched (FK ondelete=SET NULL would have cleared the
                    # link — defensive only, should not happen in practice).
                    continue
                by_issue[row.matched_issue_id] = ProjectedPullEntry(
                    pull_entry_id=row.id,
                    week=week,
                    publisher=row.publisher,
                    series_name=row.series_name,
                    issue_number=row.issue_number,
                    release_date=row.release_date,
                    cv_series_id=row.cv_series_id,
                    cv_issue_id=row.cv_issue_id,
                    match_type=row.match_type,
                    matched_issue_id=row.matched_issue_id,
                    series_id=base.series_id,
                    state=base.state,
                )
            else:
                extra.append(
                    ProjectedPullEntry(
                        pull_entry_id=row.id,
                        week=week,
                        publisher=row.publisher,
                        series_name=row.series_name,
                        issue_number=row.issue_number,
                        release_date=row.release_date,
                        cv_series_id=row.cv_series_id,
                        cv_issue_id=row.cv_issue_id,
                        match_type=row.match_type,
                        matched_issue_id=None,
                        series_id=None,
                        state=STATE_PENDING_REFRESH if _pending_refresh(row) else None,
                    )
                )

    return list(by_issue.values()) + extra
