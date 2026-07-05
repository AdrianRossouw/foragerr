"""Build the decision engine's :class:`EvaluationContext` from database rows.

The engine (``foragerr.search``) is a pure, synchronous machine over in-memory
value objects and imports nothing from the database. This module is the seam
that resolves the live library — the target series, its format profile, its
issues and on-disk files, and its user-editable aliases (FRG-SRCH-003) — into
the immutable :class:`~foragerr.search.SeriesContext` /
:class:`~foragerr.search.LibrarySnapshot` the engine consumes.

A search always targets one series, so the snapshot carries just that series:
with an engine :class:`~foragerr.search.SearchTarget` set, the search-match
specification rejects anything that does not map to the searched series/issue,
so nothing is gained by loading the whole library per search.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.db.base import utcnow
from foragerr.library.flows import decode_aliases
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow
from foragerr.library.ordering import parse_issue_number
from foragerr.parser.normalize import matching_key
from foragerr.quality.models import FormatProfileRow, decode_formats
from foragerr.search import (
    DEFAULT_CONFIG,
    EngineConfig,
    EvaluationContext,
    ExistingFile,
    FormatProfile,
    IssueContext,
    LibrarySnapshot,
    SearchTarget,
    SeriesContext,
)


def _file_format(path: str) -> str:
    """The lowercased container format from an on-disk filename (no dot)."""
    return Path(path).suffix.lstrip(".").lower()


def _alias_keys(raw_aliases: str | None, series_id: int | None = None) -> tuple[str, ...]:
    """Normalized matching keys for a series' user aliases (FRG-SRCH-003).

    Each raw alias is folded through the one shared ``matching_key`` so the
    engine compares like-for-like against a parsed release's key; blank folds
    are dropped and duplicates collapsed. A corrupt aliases value degrades to
    no keys (``decode_aliases`` logs it with ``series_id``).
    """
    keys: list[str] = []
    seen: set[str] = set()
    for raw in decode_aliases(raw_aliases, series_id=series_id):
        key = matching_key(raw)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return tuple(keys)


async def build_series_context(
    session: AsyncSession, series: SeriesRow
) -> SeriesContext | None:
    """Resolve one already-loaded library series into a :class:`SeriesContext`.

    Takes the loaded :class:`SeriesRow` (not an id) so a caller that already
    has the row does not pay a second load. On-disk files for every issue are
    fetched in one ``IssueFileRow`` ``IN()`` query rather than one query per
    issue (no N+1)."""
    profile_row = await session.get(FormatProfileRow, series.format_profile_id)
    if profile_row is None:  # pragma: no cover - FK guarantees presence
        return None
    profile = FormatProfile(
        formats=tuple(decode_formats(profile_row.formats)),
        cutoff=profile_row.cutoff,
    )

    issue_rows = (
        (
            await session.execute(
                select(IssueRow).where(IssueRow.series_id == series.id)
            )
        )
        .scalars()
        .all()
    )
    files_by_issue: dict[int, list[IssueFileRow]] = {}
    issue_ids = [r.id for r in issue_rows]
    if issue_ids:
        file_rows = (
            (
                await session.execute(
                    select(IssueFileRow).where(IssueFileRow.issue_id.in_(issue_ids))
                )
            )
            .scalars()
            .all()
        )
        for f in file_rows:
            files_by_issue.setdefault(f.issue_id, []).append(f)

    issues: list[IssueContext] = []
    for issue_row in issue_rows:
        parsed = parse_issue_number(issue_row.issue_number)
        files = tuple(
            ExistingFile(format=_file_format(f.path), size_bytes=f.size)
            for f in files_by_issue.get(issue_row.id, ())
        )
        issues.append(
            IssueContext(
                issue_id=issue_row.id,
                number=parsed.value,
                suffix=parsed.suffix,
                monitored=issue_row.monitored,
                files=files,
            )
        )

    return SeriesContext(
        series_id=series.id,
        matching_key=series.matching_key,
        profile=profile,
        aliases=_alias_keys(series.aliases, series.id),
        start_year=series.start_year,
        volume_year=series.start_year,
        monitored=series.monitored,
        issues=tuple(issues),
    )


async def build_evaluation_context(
    session: AsyncSession,
    series: SeriesRow,
    *,
    issue_id: int | None = None,
    config: EngineConfig = DEFAULT_CONFIG,
    now: datetime | None = None,
) -> EvaluationContext | None:
    """Build the full :class:`EvaluationContext` for a search over one series.

    The library snapshot is candidate- and issue-independent, so a caller can
    build it once (``issue_id=None``, no target) and stamp a per-issue
    :class:`SearchTarget` on cheaply with ``dataclasses.replace`` — that is how
    the search-command loops reuse one context across a series' wanted issues.
    ``issue_id`` set here attaches the target directly (the single-issue path).
    The change-5 dynamic-store seams keep their inert defaults."""
    series_ctx = await build_series_context(session, series)
    if series_ctx is None:
        return None
    target = (
        SearchTarget(series_id=series.id, issue_id=issue_id)
        if issue_id is not None
        else None
    )
    return EvaluationContext(
        library=LibrarySnapshot(series=(series_ctx,)),
        target=target,
        config=config,
        now=now or utcnow(),
    )
