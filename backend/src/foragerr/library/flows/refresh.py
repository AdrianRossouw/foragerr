"""Series metadata refresh: reconciliation, add-strategy, covers, chaining.

Implements FRG-META-008 (Sonarr-model reconciliation keyed by ``cv_issue_id``,
with the never-delete-on-partial-fetch and never-delete-issues-with-files
guards), FRG-SER-006 (the once-only add-time monitoring strategy) and
FRG-SER-007 (new issues monitored per the series' ``monitor_new_items``
policy). The heavy ComicVine I/O happens OUTSIDE the write transaction; all
row changes land in a single ``write_session()`` so the insert/update/delete
arms plus the metadata refresh and the ``SeriesRefreshed`` event commit
atomically.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

from foragerr.commands.service import CommandService, HandlerContext
from foragerr.config import Settings
from foragerr.db import Database, queue_event
from foragerr.db.base import utcnow
from foragerr.http import HttpClientFactory
from foragerr.library import repo
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow
from foragerr.library.ordering import ordering_key_for
from foragerr.commands.registry import register_handler
from foragerr.metadata import (
    ComicVineClient,
    ComicVineError,
    IssueRecord,
    Page,
    SeriesRecord,
    cache_cover,
)

from foragerr.library.flows._common import (
    AddOptions,
    RefreshSeriesCommand,
    SeriesRefreshed,
    comicvine_factory,
    decode_add_options,
    iso_to_date,
    monitored_for_new_items,
)

logger = logging.getLogger("foragerr.library.flows.refresh")


@dataclass(frozen=True)
class ReconcileStats:
    inserted: int
    updated: int
    deleted: int


@dataclass(frozen=True)
class RefreshResult:
    stats: ReconcileStats
    partial: bool
    applied: AddOptions | None

    def summary(self) -> str:
        return (
            f"inserted={self.stats.inserted} updated={self.stats.updated} "
            f"deleted={self.stats.deleted} partial={self.partial}"
        )


async def refresh_series(
    db: Database,
    settings: Settings,
    series_id: int,
    *,
    commands: CommandService,
    factory: HttpClientFactory | None = None,
) -> str:
    """Refresh one series' metadata and issues, then chain the scan/search.

    Returns a short human-readable summary that becomes the command's
    ``result`` in job history.
    """
    factory = factory or comicvine_factory(settings)

    async with db.read_session() as session:
        series = await repo.get_series(session, series_id)
        if series is None:
            return f"series {series_id} no longer exists; refresh skipped"
        cv_volume_id = series.cv_volume_id

    # --- ComicVine I/O: strictly OUTSIDE the write lock --------------------
    async with ComicVineClient(settings, factory) as cv:
        record: SeriesRecord = await cv.get_volume(cv_volume_id)
        page: Page[IssueRecord] = await cv.get_issues(cv_volume_id)

    # --- one write transaction: reconcile + metadata + strategy + event ----
    async with db.write_session() as session:
        series = await repo.get_series(session, series_id)
        if series is None:  # deleted between the read and the write
            return f"series {series_id} no longer exists; refresh skipped"

        stats = await _reconcile(session, series, page)

        series.publisher = record.publisher
        series.start_year = record.start_year
        series.description_sanitized = record.description
        series.refreshed_at = utcnow()

        applied = await _apply_add_strategy_once(session, series)

        queue_event(session, SeriesRefreshed(series_id, partial=not page.complete))

    result = RefreshResult(stats=stats, partial=not page.complete, applied=applied)

    # --- best-effort cover cache (network, after commit) -------------------
    await _cache_cover_best_effort(
        db, settings, factory, series_id, record.image_url
    )

    # --- chain the next steps onto the persisted backbone ------------------
    await commands.enqueue(
        "scan-series", {"series_id": series_id}, triggered_by="refresh-series"
    )
    if applied is not None and applied.search_on_add:
        await commands.enqueue(
            "series-search", {"series_id": series_id}, triggered_by="refresh-series"
        )

    logger.info("refresh series %d: %s", series_id, result.summary())
    return result.summary()


# --- reconciliation (FRG-META-008) ------------------------------------------


async def _reconcile(
    session, series: SeriesRow, page: Page[IssueRecord]
) -> ReconcileStats:
    """Insert/update/delete issues keyed by ``cv_issue_id`` in this session.

    New issues are monitored per the series' ``monitor_new_items`` policy
    (FRG-SER-007). Deletions happen ONLY when the fetch was complete and the
    absent issue has no file on disk (orphan-visible otherwise).
    """
    existing = await repo.list_issues_for_series(session, series.id)
    existing_by_cv = {row.cv_issue_id: row for row in existing}
    cv_by_id = {rec.cv_issue_id: rec for rec in page.items}

    inserted = updated = deleted = 0
    new_monitored = monitored_for_new_items(series.monitor_new_items)

    for cv_id, rec in cv_by_id.items():
        cover = iso_to_date(rec.cover_date)
        store = iso_to_date(rec.store_date)
        row = existing_by_cv.get(cv_id)
        if row is None:
            await repo.create_issue(
                session,
                series_id=series.id,
                cv_issue_id=cv_id,
                issue_number=rec.issue_number,
                title=rec.title,
                cover_date=cover,
                store_date=store,
                monitored=new_monitored,
            )
            inserted += 1
        elif _apply_issue_updates(row, rec, cover, store):
            updated += 1

    if page.complete:
        for cv_id, row in existing_by_cv.items():
            if cv_id in cv_by_id:
                continue
            has_file = await session.scalar(
                select(func.count())
                .select_from(IssueFileRow)
                .where(IssueFileRow.issue_id == row.id)
            )
            if has_file:  # never hard-delete an issue that has a file
                continue
            await session.delete(row)
            deleted += 1

    return ReconcileStats(inserted=inserted, updated=updated, deleted=deleted)


def _apply_issue_updates(
    row: IssueRow, rec: IssueRecord, cover: dt.date | None, store: dt.date | None
) -> bool:
    """Copy changed fields from the CV record onto the row; recompute the
    ordering key when the issue number changes. Returns whether anything
    changed."""
    changed = False
    if row.title != rec.title:
        row.title = rec.title
        changed = True
    if row.cover_date != cover:
        row.cover_date = cover
        changed = True
    if row.store_date != store:
        row.store_date = store
        changed = True
    if row.issue_number != rec.issue_number:
        row.issue_number = rec.issue_number
        row.ordering_key = ordering_key_for(rec.issue_number)
        changed = True
    return changed


# --- add-time monitoring strategy (FRG-SER-006) -----------------------------


async def _apply_add_strategy_once(session, series: SeriesRow) -> AddOptions | None:
    """Apply the add-time strategy over ALL current issues exactly once, then
    clear ``add_options``. A no-op (returns ``None``) once ``add_options`` is
    already null — later refreshes never re-touch monitored flags via this
    path (FRG-SER-006 "applied exactly once then cleared")."""
    opts = decode_add_options(series.add_options)
    if opts is None:
        return None

    issues = await repo.list_issues_for_series(session, series.id)
    strategy = opts.monitor_strategy

    ids_with_files: set[int] = set()
    if strategy in ("missing", "existing") and issues:
        result = await session.execute(
            select(IssueFileRow.issue_id).where(
                IssueFileRow.issue_id.in_([i.id for i in issues])
            )
        )
        ids_with_files = set(result.scalars().all())

    today = dt.date.today()
    for index, issue in enumerate(issues):
        issue.monitored = _strategy_monitored(
            strategy, index, issue, ids_with_files, today
        )

    series.add_options = None
    return opts


def _strategy_monitored(
    strategy: str,
    index: int,
    issue: IssueRow,
    ids_with_files: set[int],
    today: dt.date,
) -> bool:
    if strategy == "all":
        return True
    if strategy == "none":
        return False
    if strategy == "first":
        return index == 0  # issues arrive sorted by ordering_key (reading order)
    if strategy == "missing":
        return issue.id not in ids_with_files
    if strategy == "existing":
        return issue.id in ids_with_files
    if strategy == "future":
        release = issue.store_date or issue.cover_date
        return release is not None and release > today
    return True  # pragma: no cover - validated upstream


# --- cover cache (FRG-META-013) ---------------------------------------------


def _covers_dir(settings: Settings) -> Path:
    return Path(settings.config_dir) / "covers"


async def _cache_cover_best_effort(
    db: Database,
    settings: Settings,
    factory: HttpClientFactory,
    series_id: int,
    image_url: str | None,
) -> None:
    """Cache the series cover, re-fetching only when the CV image URL changed.

    The last-cached URL is kept in a sidecar next to the image
    (``<config>/covers/<id>.url``) rather than a schema column — the library
    models are a frozen input to this change, so a DB column would need raw
    SQL to read/write; the sidecar gives the same "re-fetch only on URL
    change" behaviour (FRG-META-013) with no migration. Any cover failure is
    logged and swallowed — a cover is a nicety, never a reason to fail the
    whole refresh.
    """
    if not image_url:
        return
    covers_dir = _covers_dir(settings)
    cover_path = covers_dir / f"{series_id}.jpg"
    url_path = covers_dir / f"{series_id}.url"

    if cover_path.exists() and url_path.exists():
        try:
            if url_path.read_text(encoding="utf-8").strip() == image_url:
                return  # unchanged URL + cached file present: reuse
        except OSError:  # pragma: no cover - unreadable sidecar: re-fetch
            pass

    try:
        await cache_cover(image_url, cover_path, factory=factory, settings=settings)
    except ComicVineError as exc:
        logger.warning("cover cache for series %d failed: %s", series_id, exc)
        return

    try:
        covers_dir.mkdir(parents=True, exist_ok=True)
        url_path.write_text(image_url, encoding="utf-8")
    except OSError as exc:  # pragma: no cover - sidecar write failure
        logger.warning("cover sidecar for series %d failed: %s", series_id, exc)

    async with db.write_session() as session:
        series = await session.get(SeriesRow, series_id)
        if series is not None:
            series.cover_cached_at = utcnow()


# --- command handler --------------------------------------------------------


@register_handler("refresh-series")
async def _handle_refresh(command: RefreshSeriesCommand, ctx: HandlerContext) -> str:
    if ctx.commands is None:  # pragma: no cover - always wired by CommandService
        raise RuntimeError("refresh-series handler needs a CommandService to chain")
    return await refresh_series(
        ctx.db,
        ctx.settings,
        command.series_id,
        commands=ctx.commands,
    )
