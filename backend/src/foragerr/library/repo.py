"""Library repository: series/issue CRUD, derived wanted, and statistics.

FRG-SER-003/004 (two-level monitoring, derived wanted), FRG-SER-009 (per-
request statistics). All write helpers take an already-open
:class:`~sqlalchemy.ext.asyncio.AsyncSession` — callers are expected to open
it via :meth:`foragerr.db.engine.Database.write_session` (writes) or
:meth:`~foragerr.db.engine.Database.read_session` (reads), per the db area's
single-writer discipline. Nothing in this module opens its own session, so
several repo calls can be composed inside one transaction (e.g. the future
add/refresh flow in change 3).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.db.base import utcnow
from foragerr.library.models import IssueFileRow, IssueRow, RootFolderRow, SeriesRow
from foragerr.library.ordering import ordering_key_for
from foragerr.parser.normalize import matching_key

# --- root folders -------------------------------------------------------


async def create_root_folder(session: AsyncSession, path: str) -> RootFolderRow:
    row = RootFolderRow(path=path)
    session.add(row)
    await session.flush()
    return row


async def list_root_folders(session: AsyncSession) -> list[RootFolderRow]:
    result = await session.execute(select(RootFolderRow).order_by(RootFolderRow.id))
    return list(result.scalars().all())


async def get_root_folder(session: AsyncSession, root_folder_id: int) -> RootFolderRow | None:
    return await session.get(RootFolderRow, root_folder_id)


async def count_series_for_root(session: AsyncSession, root_folder_id: int) -> int:
    """How many series currently reference this root (FRG-SER-008).

    Guards :func:`delete_root_folder`: a root still in use by any series must
    not be removed (the series' stored paths would dangle)."""
    count = await session.scalar(
        select(func.count())
        .select_from(SeriesRow)
        .where(SeriesRow.root_folder_id == root_folder_id)
    )
    return count or 0


async def delete_root_folder(session: AsyncSession, root_folder_id: int) -> None:
    """Delete the root-folder row only — never touches files on disk
    (FRG-SER-008). Callers resolve the not-found / still-referenced guards
    (both API-layer concerns) before calling this."""
    row = await session.get(RootFolderRow, root_folder_id)
    if row is not None:
        await session.delete(row)


# --- series ---------------------------------------------------------------


async def create_series(
    session: AsyncSession,
    *,
    cv_volume_id: int,
    title: str,
    sort_title: str | None = None,
    publisher: str | None = None,
    start_year: int | None = None,
    status: str = "continuing",
    monitored: bool = True,
    monitor_new_items: str = "all",
    format_profile_id: int,
    root_folder_id: int,
    path: str,
    description_sanitized: str | None = None,
    add_options: str | None = None,
    added_at: dt.datetime | None = None,
) -> SeriesRow:
    """Insert a series row (FRG-SER-001). Caller resolves cv_volume_id
    uniqueness/format_profile_id/root_folder_id validity beforehand — those
    are add-flow (change 3) validation concerns, not this repo's job.
    """
    row = SeriesRow(
        cv_volume_id=cv_volume_id,
        title=title,
        sort_title=sort_title or title,
        matching_key=matching_key(title),
        publisher=publisher,
        start_year=start_year,
        status=status,
        monitored=monitored,
        monitor_new_items=monitor_new_items,
        format_profile_id=format_profile_id,
        root_folder_id=root_folder_id,
        path=path,
        description_sanitized=description_sanitized,
        add_options=add_options,
        added_at=added_at or utcnow(),
    )
    session.add(row)
    await session.flush()
    return row


async def get_series(session: AsyncSession, series_id: int) -> SeriesRow | None:
    return await session.get(SeriesRow, series_id)


async def list_series(session: AsyncSession) -> list[SeriesRow]:
    result = await session.execute(select(SeriesRow).order_by(SeriesRow.sort_title))
    return list(result.scalars().all())


async def set_series_monitored(session: AsyncSession, series_id: int, monitored: bool) -> None:
    """Toggle only the series-level flag (FRG-SER-003) — never writes any
    issue-level `monitored` value."""
    row = await session.get(SeriesRow, series_id)
    if row is None:
        raise LookupError(f"no series {series_id}")
    row.monitored = monitored


# --- issues -----------------------------------------------------------------


async def create_issue(
    session: AsyncSession,
    *,
    series_id: int,
    cv_issue_id: int,
    issue_number: str | None,
    title: str | None = None,
    cover_date: dt.date | None = None,
    store_date: dt.date | None = None,
    issue_type: str = "regular",
    monitored: bool = True,
    added_at: dt.datetime | None = None,
) -> IssueRow:
    """Insert an issue row (FRG-SER-002). `monitored` here is whatever the
    caller decided (add-time strategy or monitor-new-items policy — both
    change-3 concerns); this repo just persists it."""
    row = IssueRow(
        series_id=series_id,
        cv_issue_id=cv_issue_id,
        issue_number=issue_number,
        ordering_key=ordering_key_for(issue_number),
        title=title,
        cover_date=cover_date,
        store_date=store_date,
        issue_type=issue_type,
        monitored=monitored,
        added_at=added_at or utcnow(),
    )
    session.add(row)
    await session.flush()
    return row


async def get_issue(session: AsyncSession, issue_id: int) -> IssueRow | None:
    return await session.get(IssueRow, issue_id)


async def list_issues_for_series(session: AsyncSession, series_id: int) -> list[IssueRow]:
    """Issues in reading order (FRG-SER-002) — sorted by the persisted
    ordering key, independent of insertion order."""
    result = await session.execute(
        select(IssueRow)
        .where(IssueRow.series_id == series_id)
        .order_by(IssueRow.ordering_key)
    )
    return list(result.scalars().all())


async def set_issue_monitored(session: AsyncSession, issue_id: int, monitored: bool) -> None:
    """Toggle only that issue's flag (FRG-SER-002/003) — siblings unaffected."""
    row = await session.get(IssueRow, issue_id)
    if row is None:
        raise LookupError(f"no issue {issue_id}")
    row.monitored = monitored


async def bulk_set_issue_monitored(
    session: AsyncSession, issue_ids: list[int], monitored: bool
) -> None:
    result = await session.execute(select(IssueRow).where(IssueRow.id.in_(issue_ids)))
    rows = list(result.scalars().all())
    if len(rows) != len(set(issue_ids)):
        found = {row.id for row in rows}
        missing = sorted(set(issue_ids) - found)
        raise LookupError(f"no issue(s) {missing}")
    for row in rows:
        row.monitored = monitored


# --- issue files --------------------------------------------------------


async def add_issue_file(
    session: AsyncSession,
    *,
    issue_id: int,
    path: str,
    size: int,
    added_at: dt.datetime | None = None,
) -> IssueFileRow:
    """Create an issue-file row. This alone is what removes the issue from
    `wanted_issues()` (FRG-SER-004) — no status column is written."""
    row = IssueFileRow(issue_id=issue_id, path=path, size=size, added_at=added_at or utcnow())
    session.add(row)
    await session.flush()
    return row


async def remove_issue_file(session: AsyncSession, issue_file_id: int) -> None:
    """Delete an issue-file row. This alone is what returns the issue to
    `wanted_issues()` (FRG-SER-004) — no status column is written."""
    row = await session.get(IssueFileRow, issue_file_id)
    if row is not None:
        await session.delete(row)


# --- derived wanted (FRG-SER-004) -------------------------------------------


def wanted_issues(as_of: dt.date | None = None) -> Select:
    """The reusable "wanted" selectable — a query, never a stored column.

    wanted = series.monitored AND issue.monitored AND released AND no
    issue_files row for that issue.

    "Released" prefers `store_date` (the actual on-sale date) when known,
    falling back to `cover_date`, and treats an issue with *both* dates null
    as released ("unknown-but-listed" — FRG-SER-004 note): it is already a
    real CV-catalog entry, just missing scheduling metadata, so it should
    not be withheld indefinitely.
    """
    as_of = as_of or dt.date.today()
    released = or_(
        (IssueRow.store_date.is_not(None)) & (IssueRow.store_date <= as_of),
        (IssueRow.store_date.is_(None))
        & (IssueRow.cover_date.is_not(None))
        & (IssueRow.cover_date <= as_of),
        (IssueRow.store_date.is_(None)) & (IssueRow.cover_date.is_(None)),
    )
    has_file = exists().where(IssueFileRow.issue_id == IssueRow.id)
    return (
        select(IssueRow)
        .join(SeriesRow, SeriesRow.id == IssueRow.series_id)
        .where(SeriesRow.monitored.is_(True))
        .where(IssueRow.monitored.is_(True))
        .where(released)
        .where(~has_file)
    )


async def wanted_issue_ids(session: AsyncSession, as_of: dt.date | None = None) -> list[int]:
    """Convenience: just the ids currently returned by `wanted_issues()`."""
    result = await session.execute(wanted_issues(as_of))
    return [row.id for row in result.scalars().all()]


# --- statistics (FRG-SER-009) ------------------------------------------------


@dataclass(frozen=True, slots=True)
class SeriesStatistics:
    """Per-series aggregate stats — always computed, never stored columns."""

    issue_count: int
    file_count: int
    missing_count: int
    size_on_disk: int
    next_release_date: dt.date | None
    last_release_date: dt.date | None


async def series_statistics(
    session: AsyncSession, series_id: int, as_of: dt.date | None = None
) -> SeriesStatistics:
    """Aggregate have/total, size on disk, and next/last release date.

    Every figure here is produced by aggregation at request time — there is
    no stored counter column anywhere in `library.models` (asserted by a
    schema-inventory test) to drift out of sync with the underlying rows.
    """
    as_of = as_of or dt.date.today()

    issue_count = await session.scalar(
        select(func.count()).select_from(IssueRow).where(IssueRow.series_id == series_id)
    )
    issue_count = issue_count or 0

    file_stats = (
        await session.execute(
            select(
                func.count(func.distinct(IssueRow.id)),
                func.coalesce(func.sum(IssueFileRow.size), 0),
            )
            .select_from(IssueRow)
            .join(IssueFileRow, IssueFileRow.issue_id == IssueRow.id)
            .where(IssueRow.series_id == series_id)
        )
    ).one()
    file_count, size_on_disk = file_stats
    file_count = file_count or 0
    size_on_disk = size_on_disk or 0

    release_date_expr = func.coalesce(IssueRow.store_date, IssueRow.cover_date)
    last_release_date = await session.scalar(
        select(func.max(release_date_expr)).where(
            IssueRow.series_id == series_id, release_date_expr <= as_of
        )
    )
    next_release_date = await session.scalar(
        select(func.min(release_date_expr)).where(
            IssueRow.series_id == series_id, release_date_expr > as_of
        )
    )

    return SeriesStatistics(
        issue_count=issue_count,
        file_count=file_count,
        missing_count=max(issue_count - file_count, 0),
        size_on_disk=size_on_disk,
        next_release_date=next_release_date,
        last_release_date=last_release_date,
    )
