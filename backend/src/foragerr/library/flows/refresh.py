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

from sqlalchemy import func, select, update

from foragerr.commands.service import CommandService, HandlerContext
from foragerr.config import Settings
from foragerr.creators import reconcile_series_credits
from foragerr.db import Database, queue_event
from foragerr.db.base import utcnow
from foragerr.http import HttpClientFactory
from foragerr.library import repo
from foragerr.library.booktype import detect_series_booktype
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow
from foragerr.library.ordering import ordering_key_for
from foragerr.commands.registry import register_handler
from foragerr.metadata import (
    ComicVineBudgetExhausted,
    ComicVineClient,
    ComicVineError,
    CreditRecord,
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
    cover_paths,
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
        stored_stamp = series.cv_date_last_updated
        last_walk_at = series.refreshed_at
        # Which issues already have their credits (stamped) — used to pick this
        # run's bounded credit-fetch targets. Read here so the detail fetches
        # stay OUTSIDE the write lock (FRG-CRTR-001).
        stamped_cv_ids = set(
            (
                await session.execute(
                    select(IssueRow.cv_issue_id).where(
                        IssueRow.series_id == series_id,
                        IssueRow.credits_fetched_at.is_not(None),
                    )
                )
            ).scalars().all()
        )

    # --- ComicVine I/O: strictly OUTSIDE the write lock --------------------
    async with ComicVineClient(settings, factory) as cv:
        record: SeriesRecord = await cv.get_volume(cv_volume_id)

        # Unchanged-volume short-circuit (FRG-META-017): when ComicVine's volume
        # ``date_last_updated`` matches the stamp stored by the last COMPLETE
        # walk (a non-NULL stamp implies completeness — see below) AND that walk
        # is within the staleness bound, skip the whole issue pagination walk.
        # The bound is measured against ``refreshed_at`` (the last real walk),
        # which a short-circuit deliberately does NOT bump, so a full walk still
        # runs at least every ``comicvine_refresh_max_skip_days`` as the
        # correctness backstop.
        short_circuit = _may_short_circuit(
            stored_stamp, last_walk_at, record.date_last_updated, settings
        )

        page: Page[IssueRecord] | None
        if short_circuit:
            page = None
            # Credit targets come from the DB (issues still lacking credits),
            # not a walk we skipped, so credit backfill keeps progressing on an
            # unchanged series (the common case for a large stable library).
            async with db.read_session() as session:
                target_rows = (
                    await session.execute(
                        select(
                            IssueRow.cv_issue_id,
                            IssueRow.store_date,
                            IssueRow.cover_date,
                        ).where(
                            IssueRow.series_id == series_id,
                            IssueRow.credits_fetched_at.is_(None),
                        )
                    )
                ).all()
            targets = _select_credit_targets_from_rows(
                target_rows, settings.credits_fetch_per_refresh
            )
        else:
            page = await cv.get_issues(cv_volume_id)
            targets = _select_credit_fetch_targets(
                page.items, stamped_cv_ids, settings.credits_fetch_per_refresh
            )

        # Credit fetch phase (FRG-CRTR-001): ComicVine serves person_credits
        # only on the issue DETAIL endpoint, so fetch a bounded, newest-first
        # batch of the still-credit-needing issues sequentially through the same
        # rate gate. A failed fetch is logged and skipped (the issue stays
        # unstamped and is retried next run) — never fatal to the refresh. A
        # per-path BUDGET refusal (FRG-META-016) stops the phase cleanly for
        # this run: the remaining targets stay unstamped and resume on a later
        # refresh once the window rolls; the refresh itself still succeeds.
        # Accepted (gate, m5-credits-live-fetch): two overlapping refreshes of
        # the SAME series can each spend this budget on the same unstamped
        # issues before either commits stamps — the rate gate serializes the
        # wire cost and the writes are idempotent, so no per-series in-flight
        # guard is kept.
        fetched_credits: dict[int, tuple[CreditRecord, ...]] = {}
        for cv_issue_id in targets:
            try:
                fetched_credits[cv_issue_id] = await cv.get_issue_credits(cv_issue_id)
            except ComicVineBudgetExhausted as exc:
                logger.info(
                    "credit backfill for series %d deferred: ComicVine hourly "
                    "budget for path %r exhausted, resumes in ~%.0fs "
                    "(%d issue(s) fetched this run, remainder retries later)",
                    series_id,
                    exc.bucket,
                    exc.retry_after_seconds,
                    len(fetched_credits),
                )
                break
            except ComicVineError as exc:
                logger.warning(
                    "credit detail fetch for issue %s (series %d) failed, "
                    "left for a later run: %s",
                    cv_issue_id,
                    series_id,
                    exc,
                )

    # --- one write transaction: reconcile + metadata + strategy + event ----
    async with db.write_session() as session:
        series = await repo.get_series(session, series_id)
        if series is None:  # deleted between the read and the write
            return f"series {series_id} no longer exists; refresh skipped"

        if short_circuit:
            # No issue reconcile on a short-circuit — the volume is unchanged, so
            # the local issue set is left entirely untouched (no walk, no diff).
            stats = ReconcileStats(inserted=0, updated=0, deleted=0)
            walk_complete = True
        else:
            assert page is not None
            stats = await _reconcile(session, series, page)
            walk_complete = page.complete

        # Per-issue creator credits ride the same transaction
        # (FRG-CRTR-001/002/004): reconcile the credits this run SOURCED —
        # the detail fetches above plus, on a full walk, any list rows that
        # opportunistically carried credits (detail wins on overlap) — then
        # stamp the fetched issues (INCLUDING zero-credit ones, so they are
        # never re-fetched). Reconciliation upserts creators, replaces each
        # sourced issue's credit set, and prunes orphans; it never sets
        # ``followed`` — a follow is only ever explicit (owner decision
        # 2026-07-11). Runs after the issue reconcile so deleted issues have
        # cascaded their credits and inserted issues have ids.
        credits_by_cv: dict[int, tuple[CreditRecord, ...]] = {}
        if page is not None:
            credits_by_cv = {
                rec.cv_issue_id: rec.credits
                for rec in page.items
                if rec.credits and rec.cv_issue_id not in fetched_credits
            }
        credits_by_cv.update(fetched_credits)
        await reconcile_series_credits(session, series.id, credits_by_cv)

        if fetched_credits:
            await session.execute(
                update(IssueRow)
                .where(
                    IssueRow.series_id == series.id,
                    IssueRow.cv_issue_id.in_(fetched_credits.keys()),
                )
                .values(credits_fetched_at=utcnow())
            )

        series.publisher = record.publisher
        series.start_year = record.start_year
        series.description_sanitized = record.description

        # The walk-completion stamp + refreshed_at are updated ONLY after a real
        # walk (FRG-META-017): store the CV ``date_last_updated`` after a COMPLETE
        # walk, clear it (NULL) after a partial one, so a non-NULL stamp always
        # implies the last walk completed. A short-circuit leaves both untouched
        # — the stamp still matches and ``refreshed_at`` keeps measuring age
        # since the last real walk (the staleness backstop).
        if not short_circuit:
            series.refreshed_at = utcnow()
            series.cv_date_last_updated = (
                record.date_last_updated if walk_complete else None
            )

        # Re-derive the collected-edition book-type unless the operator locked
        # it (FRG-SER-018) — refresh never changes ``series.title``, so this is
        # stable across refreshes (same reasoning as grouping); display/naming
        # only, never touches wanted state (FRG-SER-019).
        if not series.booktype_locked:
            series.booktype = detect_series_booktype(series.title)

        # Re-derive the franchise group unless the operator locked it
        # (FRG-SER-016/017) — display-only; never touches issues/wanted.
        await repo.apply_autogrouping(session, series)

        applied = await _apply_add_strategy_once(session, series)

        queue_event(session, SeriesRefreshed(series_id, partial=not walk_complete))

    result = RefreshResult(stats=stats, partial=not walk_complete, applied=applied)

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


# --- unchanged-volume short-circuit (FRG-META-017) --------------------------


def _may_short_circuit(
    stored_stamp: str | None,
    last_walk_at: dt.datetime | None,
    fetched_stamp: str | None,
    settings: Settings,
) -> bool:
    """Whether this refresh may skip the issue walk (FRG-META-017).

    True only when ALL hold: a stamp was stored (non-NULL ⇒ the last walk was
    complete), ComicVine's freshly fetched ``date_last_updated`` equals it
    (verbatim equality — never parsed), and the last walk is within the
    configured staleness bound. A NULL stamp (no complete walk yet, or the last
    walk was partial), a changed value, an absent ``refreshed_at``, or an
    over-bound age all force the full walk.
    """
    if stored_stamp is None or last_walk_at is None:
        return False
    if fetched_stamp is None or fetched_stamp != stored_stamp:
        return False
    skip_days = max(1, settings.comicvine_refresh_max_skip_days)
    return (utcnow() - last_walk_at) <= dt.timedelta(days=skip_days)


# --- credit fetch targeting (FRG-CRTR-001) ----------------------------------


def _select_credit_targets_from_rows(
    rows: "list",
    bound: int,
) -> list[int]:
    """Pick bounded, newest-first credit-fetch targets on the short-circuit path.

    ``rows`` are ``(cv_issue_id, store_date, cover_date)`` tuples of the series'
    DB issues still lacking credits (``credits_fetched_at IS NULL``). Ordered
    newest-first exactly like :func:`_select_credit_fetch_targets` — ``store_date``
    DESC with NULLs last, then ``cover_date`` DESC, then ``cv_issue_id`` DESC —
    and capped at ``bound``. The DB dates are ``date`` objects; a missing date
    sorts as ``date.min`` which, under ``reverse=True``, lands last (NULLS LAST).
    """
    ordered = sorted(
        rows,
        key=lambda r: (
            r.store_date or dt.date.min,
            r.cover_date or dt.date.min,
            r.cv_issue_id,
        ),
        reverse=True,
    )
    return [r.cv_issue_id for r in ordered[:bound]]


def _select_credit_fetch_targets(
    records: "tuple[IssueRecord, ...]",
    stamped_cv_ids: set[int],
    bound: int,
) -> list[int]:
    """Pick this run's bounded, newest-first credit-fetch targets.

    From the walk's issue records, drop those already credit-covered (a stamped
    ``cv_issue_id``), order the rest newest-first — ``store_date`` DESC with
    NULLs last, then ``cover_date`` DESC, then ``cv_issue_id`` DESC — and take
    at most ``bound`` (design decision 1: current books matter most on screens;
    the tail backfills across subsequent runs). ISO date strings sort
    chronologically; a missing date becomes ``""`` which, under ``reverse=True``,
    sorts last — giving the NULLS-LAST ordering. Fetching by ``cv_issue_id``
    (available straight from the walk) means brand-new issues are eligible the
    same run without needing their local ids yet.
    """
    needing = [rec for rec in records if rec.cv_issue_id not in stamped_cv_ids]
    needing.sort(
        key=lambda rec: (
            rec.store_date or "",
            rec.cover_date or "",
            rec.cv_issue_id,
        ),
        reverse=True,
    )
    return [rec.cv_issue_id for rec in needing[:bound]]


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

    Ordering note: the DB's ``cover_cached_at`` is updated BEFORE the sidecar
    is written (not after). If the process dies between the JPEG write and
    the DB commit, the next refresh sees the JPEG but no sidecar and simply
    re-fetches (harmless extra work). If it dies between the DB commit and
    the sidecar write, the next refresh also re-fetches (the "already
    cached" skip check requires both files) rather than silently leaving
    ``cover_cached_at`` stuck at a stale value — the DB is the durable source
    of truth, the sidecar only helps that following refresh detect the
    cover has already been recorded.
    """
    if not image_url:
        return
    cover_path, url_path = cover_paths(settings, series_id)

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

    async with db.write_session() as session:
        series = await session.get(SeriesRow, series_id)
        if series is not None:
            series.cover_cached_at = utcnow()
            # Announce the newly cached cover on the event stream in the SAME
            # transaction that records it (FRG-META-013): the frontend versions
            # cover URLs by ``cover_cached_at`` and repaints on SeriesRefreshed,
            # so this closes the "cover arrived but the open page never learns"
            # gap. Reached only when a cover was actually (re)fetched — the
            # unchanged-URL early return above emits nothing, so steady-state
            # refreshes don't double-invalidate. ``partial=False``: a cover
            # write never implies an incomplete issue walk.
            queue_event(session, SeriesRefreshed(series_id, partial=False))

    try:
        cover_path.parent.mkdir(parents=True, exist_ok=True)
        url_path.write_text(image_url, encoding="utf-8")
    except OSError as exc:  # pragma: no cover - sidecar write failure
        logger.warning("cover sidecar for series %d failed: %s", series_id, exc)


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
