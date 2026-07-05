"""Concise builders for search-engine tests (imported as ``from builders import``).

Mirrors the ``tests/parser`` convention (no package ``__init__``; the test
directory is on ``sys.path`` under pytest's prepend import mode).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from fractions import Fraction

from foragerr.releases import ReleaseCandidate
from foragerr.search import (
    EngineConfig,
    EvaluationContext,
    ExistingFile,
    FormatProfile,
    IssueContext,
    LibrarySnapshot,
    SearchTarget,
    SeriesContext,
)

NOW = datetime(2026, 7, 5, 12, 0, 0)

DEFAULT_PROFILE = FormatProfile(formats=("pdf", "cbr", "cbz"), cutoff="cbz")


def candidate(
    title: str,
    *,
    guid: str = "guid-1",
    indexer_id: int = 1,
    indexer_name: str = "DogNZB",
    indexer_priority: int = 1,
    query_tier: int = 0,
    size_bytes: int | None = 30_000_000,
    pub_date: datetime | None = None,
    age_hours: float | None = None,
) -> ReleaseCandidate:
    """Build a candidate; ``age_hours`` sets ``pub_date`` relative to ``NOW``."""
    if age_hours is not None:
        pub_date = NOW - timedelta(hours=age_hours)
    return ReleaseCandidate(
        guid=guid,
        title=title,
        link=f"https://example/{guid}.nzb",
        indexer_id=indexer_id,
        indexer_name=indexer_name,
        indexer_priority=indexer_priority,
        query_tier=query_tier,
        size_bytes=size_bytes,
        pub_date=pub_date,
    )


def issue(
    issue_id: int,
    number: int | Fraction,
    *,
    suffix: str | None = None,
    files: tuple[ExistingFile, ...] = (),
) -> IssueContext:
    value = number if isinstance(number, Fraction) else Fraction(number)
    return IssueContext(issue_id=issue_id, number=value, suffix=suffix, files=files)


def series(
    series_id: int,
    matching_key: str,
    *,
    issues: tuple[IssueContext, ...] = (),
    aliases: tuple[str, ...] = (),
    start_year: int | None = None,
    volume_year: int | None = None,
    profile: FormatProfile = DEFAULT_PROFILE,
) -> SeriesContext:
    return SeriesContext(
        series_id=series_id,
        matching_key=matching_key,
        profile=profile,
        aliases=aliases,
        start_year=start_year,
        volume_year=volume_year,
        issues=issues,
    )


def context(
    *serieses: SeriesContext,
    target: SearchTarget | None = None,
    config: EngineConfig | None = None,
    now: datetime = NOW,
    queue=None,
    blocklist=None,
    free_space=None,
) -> EvaluationContext:
    kwargs: dict = {
        "library": LibrarySnapshot(series=tuple(serieses)),
        "target": target,
        "now": now,
    }
    if config is not None:
        kwargs["config"] = config
    if queue is not None:
        kwargs["queue"] = queue
    if blocklist is not None:
        kwargs["blocklist"] = blocklist
    if free_space is not None:
        kwargs["free_space"] = free_space
    return EvaluationContext(**kwargs)
