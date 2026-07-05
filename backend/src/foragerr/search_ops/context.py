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


def _alias_keys(raw_aliases: str | None) -> tuple[str, ...]:
    """Normalized matching keys for a series' user aliases (FRG-SRCH-003).

    Each raw alias is folded through the one shared ``matching_key`` so the
    engine compares like-for-like against a parsed release's key; blank folds
    are dropped and duplicates collapsed.
    """
    keys: list[str] = []
    seen: set[str] = set()
    for raw in decode_aliases(raw_aliases):
        key = matching_key(raw)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return tuple(keys)


async def build_series_context(
    session: AsyncSession, series_id: int
) -> SeriesContext | None:
    """Resolve one library series into a :class:`SeriesContext`, or ``None``."""
    series = await session.get(SeriesRow, series_id)
    if series is None:
        return None

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
                select(IssueRow).where(IssueRow.series_id == series_id)
            )
        )
        .scalars()
        .all()
    )
    issues: list[IssueContext] = []
    for issue_row in issue_rows:
        parsed = parse_issue_number(issue_row.issue_number)
        file_rows = (
            (
                await session.execute(
                    select(IssueFileRow).where(
                        IssueFileRow.issue_id == issue_row.id
                    )
                )
            )
            .scalars()
            .all()
        )
        files = tuple(
            ExistingFile(format=_file_format(f.path), size_bytes=f.size)
            for f in file_rows
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
        aliases=_alias_keys(series.aliases),
        start_year=series.start_year,
        volume_year=series.start_year,
        monitored=series.monitored,
        issues=tuple(issues),
    )


async def build_evaluation_context(
    session: AsyncSession,
    series_id: int,
    *,
    issue_id: int | None = None,
    config: EngineConfig = DEFAULT_CONFIG,
    now: datetime | None = None,
) -> EvaluationContext | None:
    """Build the full :class:`EvaluationContext` for a search over one series.

    ``issue_id`` set makes this a search-path evaluation (an engine
    :class:`SearchTarget` is attached, so the search-match specification
    verifies each candidate maps to the searched series+issue). ``None``
    yields a plain mapping evaluation (no target). The change-5 dynamic-store
    seams (queue / blocklist / free-space) keep their inert defaults here.
    """
    series_ctx = await build_series_context(session, series_id)
    if series_ctx is None:
        return None
    target = (
        SearchTarget(series_id=series_id, issue_id=issue_id)
        if issue_id is not None
        else None
    )
    return EvaluationContext(
        library=LibrarySnapshot(series=(series_ctx,)),
        target=target,
        config=config,
        now=now or utcnow(),
    )
