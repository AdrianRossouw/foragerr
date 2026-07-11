"""The creators HTTP surface (FRG-API-023).

Read + follow-toggle over the creators backbone, all computed from STORED
credits (:mod:`foragerr.creators` / ``issue_credits``). Every aggregate here is
a plain DB query: this router constructs no ComicVine client and issues no
ComicVine request (asserted by a test), and it exposes no secret and no raw
(unsanitized) CV string — creator names and role tokens were sanitized at
ingest (FRG-CRTR-001) and are re-served verbatim, never re-fetched.

Three routes:

* ``GET /api/v1/creators`` — paged creator rows for the grid, each with the
  normalized role set, distinct-library-series count, ``followed`` flag, and a
  bounded set of library work references (series id / title / cover
  availability) for the card spine. The envelope carries the grid-header
  aggregates (``totalCreators`` / ``followedCreators``). Sortable by ``name``
  (default) / ``seriesCount``; filterable to followed-only. The projection is
  composed and paged in-process, like the pull / franchise-group projections.
* ``GET /api/v1/creators/{id}`` — the profile aggregates: per-series roles,
  owned/total issue counts, and the distinct publisher count.
* ``PUT /api/v1/creators/{id}/follow`` — the user-owned follow toggle (mirroring
  the issue monitored toggle's PUT-sub-resource shape); it writes ONLY the flag
  (and its user-touched marker, FRG-CRTR-004) and returns the updated row.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.api.errors import ApiError
from foragerr.creators import repo as creators_repo
from foragerr.creators.models import CreatorRow, IssueCreditRow
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow

router = APIRouter(prefix="/creators", tags=["creators"])

_SORT_DIRECTIONS = ("asc", "desc")
#: Sort keys for the creators grid (FRG-API-023). ``seriesCount`` sorts on the
#: computed distinct-series aggregate, so the projection is sorted in-process
#: (mirroring the pull / franchise-group projections) rather than in SQL.
_SORT_KEYS = ("name", "seriesCount")

#: Cap on the work references shipped per grid row (card spine). Small and fixed
#: so a prolific creator's row stays bounded.
WORKS_CAP = 6


# --- resource models ---------------------------------------------------------


class CreatorWorkRef(BaseModel):
    """One library work reference on a creator grid row (FRG-API-023): a series
    the creator has credits in, with its cover availability so the card spine can
    render (or skip) the cover without a second call."""

    seriesId: int
    title: str
    coverAvailable: bool


class CreatorResource(BaseModel):
    """One creators-grid row (FRG-API-023)."""

    id: int
    name: str
    roles: list[str]
    seriesCount: int
    followed: bool
    works: list[CreatorWorkRef]


class CreatorPage(BaseModel):
    """Paging envelope (FRG-API-002) specialized for creator rows, plus the
    grid-header aggregate counts (FRG-API-023)."""

    page: int
    pageSize: int
    sortKey: str
    sortDirection: str
    totalRecords: int
    records: list[CreatorResource]
    totalCreators: int
    followedCreators: int


class CreatorSeriesStat(BaseModel):
    """One per-series row on a creator profile (FRG-API-023)."""

    seriesId: int
    title: str
    publisher: str | None
    roles: list[str]
    ownedIssues: int
    totalIssues: int


class CreatorStats(BaseModel):
    """Roll-up stats on a creator profile (FRG-API-023)."""

    seriesCount: int
    ownedIssues: int
    totalIssues: int
    publisherCount: int


class CreatorProfile(BaseModel):
    """``GET /api/v1/creators/{id}`` profile response (FRG-API-023)."""

    id: int
    name: str
    roles: list[str]
    followed: bool
    stats: CreatorStats
    series: list[CreatorSeriesStat]


class CreatorFollowUpdate(BaseModel):
    """Request body for ``PUT /api/v1/creators/{id}/follow``."""

    followed: bool


# --- shared aggregate helpers ------------------------------------------------


async def _series_count_by_creator(session: AsyncSession) -> dict[int, int]:
    """Distinct-library-series count per creator (one grouped, indexed query)."""
    rows = await session.execute(
        select(
            IssueCreditRow.creator_id,
            func.count(func.distinct(IssueRow.series_id)),
        )
        .join(IssueRow, IssueRow.id == IssueCreditRow.issue_id)
        .group_by(IssueCreditRow.creator_id)
    )
    return {creator_id: int(count) for creator_id, count in rows}


async def _series_count_for_creator(session: AsyncSession, creator_id: int) -> int:
    """Distinct-library-series count for a SINGLE creator (indexed lookup).

    The follow-toggle path rebuilds one row, so it uses this creator-scoped query
    rather than the whole-library GROUP BY in :func:`_series_count_by_creator`
    (which the list path still wants, since it counts every creator at once)."""
    return int(
        await session.scalar(
            select(func.count(func.distinct(IssueRow.series_id)))
            .select_from(IssueCreditRow)
            .join(IssueRow, IssueRow.id == IssueCreditRow.issue_id)
            .where(IssueCreditRow.creator_id == creator_id)
        )
        or 0
    )


async def _roles_by_creator(
    session: AsyncSession, creator_ids: list[int]
) -> dict[int, list[str]]:
    """Sorted normalized-role set per creator, for the given ids."""
    result: dict[int, set[str]] = {cid: set() for cid in creator_ids}
    if not creator_ids:
        return {}
    rows = await session.execute(
        select(IssueCreditRow.creator_id, IssueCreditRow.role_normalized)
        .where(IssueCreditRow.creator_id.in_(creator_ids))
        .distinct()
    )
    for creator_id, role in rows:
        result[creator_id].add(role)
    return {cid: sorted(roles) for cid, roles in result.items()}


async def _works_by_creator(
    session: AsyncSession, creator_ids: list[int]
) -> dict[int, list[CreatorWorkRef]]:
    """Up to :data:`WORKS_CAP` stable-ordered work refs per creator, for the ids.

    Ordered by the series' sort title then id so a row's card spine is
    deterministic across requests. Cover availability is the presence of a cached
    cover (``series.cover_cached_at``), mirroring how the series cover endpoint
    resolves a cached JPEG by series id."""
    result: dict[int, list[CreatorWorkRef]] = {cid: [] for cid in creator_ids}
    if not creator_ids:
        return {}
    rows = await session.execute(
        select(
            IssueCreditRow.creator_id,
            SeriesRow.id,
            SeriesRow.title,
            SeriesRow.sort_title,
            SeriesRow.cover_cached_at,
        )
        .join(IssueRow, IssueRow.id == IssueCreditRow.issue_id)
        .join(SeriesRow, SeriesRow.id == IssueRow.series_id)
        .where(IssueCreditRow.creator_id.in_(creator_ids))
        .distinct()
        .order_by(SeriesRow.sort_title, SeriesRow.id)
    )
    for creator_id, series_id, title, _sort_title, cover_cached_at in rows:
        works = result[creator_id]
        if len(works) >= WORKS_CAP:
            continue
        works.append(
            CreatorWorkRef(
                seriesId=series_id,
                title=title,
                coverAvailable=cover_cached_at is not None,
            )
        )
    return result


async def _build_row(
    session: AsyncSession, row: CreatorRow
) -> CreatorResource:
    """Assemble one creator's grid row resource (reused by the follow toggle)."""
    roles = (await _roles_by_creator(session, [row.id]))[row.id]
    works = (await _works_by_creator(session, [row.id]))[row.id]
    series_count = await _series_count_for_creator(session, row.id)
    return CreatorResource(
        id=row.id,
        name=row.name,
        roles=roles,
        seriesCount=series_count,
        followed=row.followed,
        works=works,
    )


# --- routes ------------------------------------------------------------------


@router.get("", response_model=CreatorPage)
async def list_creators(
    request: Request,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortKey: str = Query("name"),
    sortDirection: str = Query("asc"),
    followed: bool | None = Query(None),
    seriesId: int | None = Query(None, ge=1),
) -> CreatorPage:
    """The creators grid (FRG-API-023): a paged, in-process projection.

    ``followed=true`` filters the returned rows to followed creators only.
    ``seriesId`` (the series-detail focus chip, FRG-UI-027) filters the rows to
    creators credited in that one series; it composes with the followed filter
    and with paging. An unknown ``seriesId`` matches no creator and yields an
    empty ``records`` list. ``seriesId`` is validated ``ge=1`` (a non-positive or
    non-integer value is a 400).

    The header aggregates (``totalCreators`` / ``followedCreators``) are ALWAYS
    the whole-library counts, independent of BOTH filters: per the grid-header
    design (FRG-UI-027) the header count line is global (``N creators · M
    followed``) while the focus chip merely narrows the visible cards. So the
    filters shape ``records``/``totalRecords`` only; the aggregates stay global.
    No ComicVine request is issued."""
    if sortDirection not in _SORT_DIRECTIONS:
        raise ApiError(
            400,
            f"sortDirection must be one of {_SORT_DIRECTIONS} (got {sortDirection!r})",
            field="sortDirection",
        )
    if sortKey not in _SORT_KEYS:
        raise ApiError(
            400,
            f"unknown sortKey {sortKey!r}; must be one of {sorted(_SORT_KEYS)}",
            field="sortKey",
        )

    db = request.app.state.db
    async with db.read_session() as session:
        # Header aggregates — whole-library, independent of the followed filter.
        total_creators = int(
            await session.scalar(select(func.count()).select_from(CreatorRow)) or 0
        )
        followed_creators = int(
            await session.scalar(
                select(func.count())
                .select_from(CreatorRow)
                .where(CreatorRow.followed.is_(True))
            )
            or 0
        )

        stmt = select(CreatorRow)
        if followed is True:
            stmt = stmt.where(CreatorRow.followed.is_(True))
        if seriesId is not None:
            # Focus chip (FRG-UI-027): restrict to creators credited in this one
            # series. Composes with the followed filter and paging; an unknown
            # series id matches nothing (empty records, global aggregates intact).
            credited_in_series = (
                select(IssueCreditRow.creator_id)
                .join(IssueRow, IssueRow.id == IssueCreditRow.issue_id)
                .where(IssueRow.series_id == seriesId)
            )
            stmt = stmt.where(CreatorRow.id.in_(credited_in_series))
        creators = list((await session.execute(stmt)).scalars().all())

        series_counts = await _series_count_by_creator(session)

        reverse = sortDirection == "desc"
        if sortKey == "seriesCount":
            creators.sort(
                key=lambda c: (series_counts.get(c.id, 0), c.name.casefold(), c.id),
                reverse=reverse,
            )
        else:  # name
            creators.sort(key=lambda c: (c.name.casefold(), c.id), reverse=reverse)

        total = len(creators)
        start = (page - 1) * pageSize
        window = creators[start : start + pageSize]
        page_ids = [c.id for c in window]

        roles_by = await _roles_by_creator(session, page_ids)
        works_by = await _works_by_creator(session, page_ids)

        records = [
            CreatorResource(
                id=c.id,
                name=c.name,
                roles=roles_by.get(c.id, []),
                seriesCount=series_counts.get(c.id, 0),
                followed=c.followed,
                works=works_by.get(c.id, []),
            )
            for c in window
        ]

    return CreatorPage(
        page=page,
        pageSize=pageSize,
        sortKey=sortKey,
        sortDirection=sortDirection,
        totalRecords=total,
        records=records,
        totalCreators=total_creators,
        followedCreators=followed_creators,
    )


@router.get("/{creator_id}", response_model=CreatorProfile)
async def get_creator_profile(creator_id: int, request: Request) -> CreatorProfile:
    """A creator profile (FRG-API-023): per-series roles + owned/total issue
    counts + the distinct publisher count, all from stored credits. Unknown id
    -> 404 in the uniform error shape. No ComicVine request is issued."""
    db = request.app.state.db
    async with db.read_session() as session:
        creator = await creators_repo.get_creator(session, creator_id)
        if creator is None:
            raise ApiError(404, f"creator {creator_id} not found")

        # One row per (series, role) this creator is credited in — the basis for
        # the per-series role sets and the set of series the profile spans.
        rows = list(
            await session.execute(
                select(
                    IssueRow.series_id,
                    SeriesRow.title,
                    SeriesRow.publisher,
                    IssueCreditRow.role_normalized,
                )
                .join(IssueRow, IssueRow.id == IssueCreditRow.issue_id)
                .join(SeriesRow, SeriesRow.id == IssueRow.series_id)
                .where(IssueCreditRow.creator_id == creator_id)
                .distinct()
            )
        )

        # owned/total counts are WHOLE-SERIES (FRG-API-023: "owned/total issue
        # counts across those series") — the profile's progress bars track each
        # credited series' overall progress, not just the issues the creator is
        # credited on. Count over ALL issues of every series the creator touches.
        series_ids = {series_id for series_id, _, _, _ in rows}
        total_by_series: dict[int, int] = {}
        owned_by_series: dict[int, int] = {}
        if series_ids:
            total_by_series = {
                sid: int(n)
                for sid, n in await session.execute(
                    select(IssueRow.series_id, func.count())
                    .where(IssueRow.series_id.in_(series_ids))
                    .group_by(IssueRow.series_id)
                )
            }
            owned_by_series = {
                sid: int(n)
                for sid, n in await session.execute(
                    select(
                        IssueRow.series_id,
                        func.count(func.distinct(IssueRow.id)),
                    )
                    .join(IssueFileRow, IssueFileRow.issue_id == IssueRow.id)
                    .where(IssueRow.series_id.in_(series_ids))
                    .group_by(IssueRow.series_id)
                )
            }

    # Aggregate the per-series role sets in memory over the small credited set;
    # the owned/total counts come from the whole-series aggregates above.
    per_series: dict[int, dict] = {}
    for series_id, title, publisher, role in rows:
        entry = per_series.setdefault(
            series_id,
            {"title": title, "publisher": publisher, "roles": set()},
        )
        entry["roles"].add(role)

    series_stats: list[CreatorSeriesStat] = []
    for series_id, entry in per_series.items():
        series_stats.append(
            CreatorSeriesStat(
                seriesId=series_id,
                title=entry["title"],
                publisher=entry["publisher"],
                roles=sorted(entry["roles"]),
                ownedIssues=owned_by_series.get(series_id, 0),
                totalIssues=total_by_series.get(series_id, 0),
            )
        )
    series_stats.sort(key=lambda s: (s.title.casefold(), s.seriesId))

    all_roles = sorted({role for _, _, _, role in rows})
    publishers = {
        entry["publisher"] for entry in per_series.values() if entry["publisher"]
    }
    stats = CreatorStats(
        seriesCount=len(per_series),
        ownedIssues=sum(s.ownedIssues for s in series_stats),
        totalIssues=sum(s.totalIssues for s in series_stats),
        publisherCount=len(publishers),
    )

    return CreatorProfile(
        id=creator.id,
        name=creator.name,
        roles=all_roles,
        followed=creator.followed,
        stats=stats,
        series=series_stats,
    )


@router.put("/{creator_id}/follow", response_model=CreatorResource)
async def set_follow(
    creator_id: int, body: CreatorFollowUpdate, request: Request
) -> CreatorResource:
    """Toggle a creator's user-owned follow flag (FRG-API-023 / FRG-CRTR-004).

    Writes ONLY the flag and its ``follow_touched`` marker (via
    ``repo.set_creator_followed``) — no series/issue/search state changes — then
    returns the updated grid row read back inside the same write session (the
    single-writer lock spans the toggle and re-read, so no concurrent delete can
    race between them, mirroring the issue monitored toggle). Unknown id -> 404."""
    db = request.app.state.db
    try:
        async with db.write_session() as session:
            row = await creators_repo.set_creator_followed(
                session, creator_id, body.followed
            )
            resource = await _build_row(session, row)
    except LookupError as exc:
        raise ApiError(404, str(exc)) from exc
    return resource


__all__ = ["router"]
