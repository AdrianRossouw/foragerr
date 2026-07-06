"""Series HTTP surface (FRG-API-003, FRG-API-006, FRG-META-013).

Thin translation layer over the frozen ``foragerr.library``/``foragerr.library.
repo`` and ``foragerr.library.flows`` packages, plus a live (non-persisting)
ComicVine lookup via ``foragerr.metadata``. No business logic lives here —
every mutation rides a flows entrypoint (``add_series``/``edit_series``/
``delete_series``); this module only shapes HTTP in/out and maps flow
exceptions to the uniform error shape.

URL naming note: the design doc uses plural ``series``/``issues`` router
names; one spec scenario's illustrative text writes the singular
``/api/v1/issue``. Plural is used throughout (including here, transitively,
via the sibling ``issues`` router) so the bulk collection action
``PUT /api/v1/issues/monitor`` reads unambiguously alongside the single-
resource ``PUT /api/v1/issues/{id}``.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import asdict
from pathlib import Path

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from foragerr.api.command import CommandResource
from foragerr.api.errors import ApiError
from foragerr.api.paging import paginate
from foragerr.commands import CommandValidationError
from foragerr.library import repo
from foragerr.library.flows import (
    MAX_ALIAS_LENGTH,
    SeriesNotFoundError,
    SeriesValidationError,
    add_series,
    comicvine_factory,
    decode_aliases,
    delete_series,
    edit_series,
)
from foragerr.library.models import SeriesRow
from foragerr.library.repo import SeriesStatistics
from foragerr.metadata import (
    COMICVINE_CREDENTIAL_MESSAGE,
    ComicVineAuthError,
    ComicVineClient,
    ComicVineError,
)

logger = logging.getLogger("foragerr.api.series")

router = APIRouter(prefix="/series", tags=["series"])

#: Whitelisted sort keys -> fixed column expressions (FRG-API-006); the
#: client-supplied sortKey string is never interpolated into SQL.
_SORT_WHITELIST = {
    "title": SeriesRow.title,
    "sort_title": SeriesRow.sort_title,
    "added_at": SeriesRow.added_at,
}

#: Upstream ComicVine failures of any kind map to one consistent status: the
#: metadata dependency is unreachable/misbehaving, which is a 503 (Service
#: Unavailable) from foragerr's own API's point of view, not a client error.
_COMICVINE_LOOKUP_ERROR_STATUS = 503


# --- resource models ---------------------------------------------------------


class SeriesStatisticsResource(BaseModel):
    """Per-series aggregate stats (FRG-SER-009) — always computed fresh."""

    issue_count: int
    file_count: int
    missing_count: int
    size_on_disk: int
    next_release_date: dt.date | None
    last_release_date: dt.date | None

    @classmethod
    def from_stats(cls, stats: SeriesStatistics) -> "SeriesStatisticsResource":
        return cls(**asdict(stats))


def _series_fields(row: SeriesRow, stats: SeriesStatistics) -> dict:
    """The shared field dict for both ``SeriesResource`` and
    ``SeriesCreateResponse`` (which adds one field on top) — a single place
    to keep the row->resource field mapping, rather than duplicating it or
    reaching into a constructed model's ``__dict__``."""
    return {
        "id": row.id,
        "cv_volume_id": row.cv_volume_id,
        "title": row.title,
        "sort_title": row.sort_title,
        "publisher": row.publisher,
        "start_year": row.start_year,
        "status": row.status,
        "monitored": row.monitored,
        "monitor_new_items": row.monitor_new_items,
        "format_profile_id": row.format_profile_id,
        "root_folder_id": row.root_folder_id,
        "path": row.path,
        "cover_cached_at": row.cover_cached_at,
        "added_at": row.added_at,
        "refreshed_at": row.refreshed_at,
        "description_sanitized": row.description_sanitized,
        "aliases": list(decode_aliases(row.aliases, series_id=row.id)),
        "statistics": SeriesStatisticsResource.from_stats(stats),
    }


class SeriesResource(BaseModel):
    """A series resource (snake_case fields, matching ``command.py``'s
    convention — only the paging envelope's OWN keys are camelCase)."""

    id: int
    cv_volume_id: int
    title: str
    sort_title: str
    publisher: str | None
    start_year: int | None
    status: str
    monitored: bool
    monitor_new_items: str
    format_profile_id: int
    root_folder_id: int
    path: str
    cover_cached_at: dt.datetime | None
    added_at: dt.datetime
    refreshed_at: dt.datetime | None
    description_sanitized: str | None
    #: User-editable alternate search names the search engine maps releases
    #: through (FRG-SRCH-003). Empty when the series has none.
    aliases: list[str]
    statistics: SeriesStatisticsResource

    @classmethod
    def from_row_and_stats(
        cls, row: SeriesRow, stats: SeriesStatistics
    ) -> "SeriesResource":
        return cls(**_series_fields(row, stats))


class SeriesPage(BaseModel):
    """Paging envelope (FRG-API-006) specialized for series resources."""

    page: int
    pageSize: int
    sortKey: str
    sortDirection: str
    totalRecords: int
    records: list[SeriesResource]


class SeriesCreate(BaseModel):
    """Request body for ``POST /api/v1/series`` (write-only add options)."""

    cv_volume_id: int
    root_folder_id: int
    format_profile_id: int | None = None
    monitor_strategy: str = "all"
    monitor_new_items: str = "all"
    search_on_add: bool = False
    path: str | None = None


class SeriesCreateResponse(SeriesResource):
    """The created series plus the id of the queued refresh command."""

    refresh_command_id: int

    @classmethod
    def from_row_stats_and_command(
        cls, row: SeriesRow, stats: SeriesStatistics, refresh_command_id: int
    ) -> "SeriesCreateResponse":
        return cls(**_series_fields(row, stats), refresh_command_id=refresh_command_id)


class SeriesEdit(BaseModel):
    """Request body for ``PUT /api/v1/series/{id}``; ``None`` = don't change
    (mirrors ``edit_series``'s own kwargs semantics exactly)."""

    monitored: bool | None = None
    monitor_new_items: str | None = None
    format_profile_id: int | None = None
    root_folder_id: int | None = None
    path: str | None = None
    #: When supplied, REPLACES the stored alternate search names wholesale
    #: (FRG-SRCH-003); pass ``[]`` to clear. ``None`` leaves them unchanged.
    #: Each alias is capped at ``MAX_ALIAS_LENGTH`` chars (422 otherwise), the
    #: pydantic mirror of the flow-level ``validate_aliases`` bound.
    aliases: list[Annotated[str, Field(max_length=MAX_ALIAS_LENGTH)]] | None = None


class LookupCandidateResource(BaseModel):
    """One ComicVine search candidate annotated with plausibility signals
    (FRG-META-007) and library membership (``have_it``)."""

    cv_volume_id: int
    name: str | None
    publisher: str | None
    start_year: int | None
    #: ComicVine issue count for the volume (FRG-META-007) — lets the add
    #: screen show how many issues a candidate has; ``None`` when ComicVine
    #: did not supply it.
    count_of_issues: int | None
    image_url: str | None
    name_similarity: float
    year_proximity: int | None
    target_issue_plausible: bool | None
    have_it: bool


class LookupResponse(BaseModel):
    """Lookup outcome envelope (FRG-API-003). ``complete`` carries the
    pagination walk's completeness so a degraded partial walk
    (``complete=False``) is distinguishable from a clean, complete empty
    result (``complete=True, records=[]``); ``truncated`` marks a walk
    deliberately stopped at the configured result cap (retry cannot help —
    narrow the term), distinct from a transient degrade (retry may help).
    An auth failure never reaches here — it maps to a 503 error response
    instead."""

    records: list[LookupCandidateResource]
    complete: bool
    truncated: bool


# --- routes -------------------------------------------------------------------


@router.get("", response_model=SeriesPage)
async def list_series(
    request: Request,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortKey: str = Query("sort_title"),
    sortDirection: str = Query("asc"),
) -> SeriesPage:
    """Paged series index with nested statistics (FRG-API-003, FRG-API-006).

    ``repo.series_statistics()`` runs several small aggregate queries per
    row (issue count, file count/size, next/last release date) — a known
    N+1 across the page (up to ~4 * pageSize queries), acceptable at M1
    scale (int aggregates over indexed FKs, no heavy joins) but NOT free;
    not fixed here (see the API-area report for rationale)."""
    db = request.app.state.db
    async with db.read_session() as session:
        result = await paginate(
            session,
            stmt=select(SeriesRow),
            page=page,
            page_size=pageSize,
            sort_key=sortKey,
            sort_direction=sortDirection,
            whitelist=_SORT_WHITELIST,
        )
        records = []
        for row in result["records"]:
            stats = await repo.series_statistics(session, row.id)
            records.append(SeriesResource.from_row_and_stats(row, stats))
    result["records"] = records
    return SeriesPage(**result)


# NOTE: registered BEFORE "/{series_id}" so "lookup" is never swallowed by
# the int-typed path parameter.
@router.get("/lookup", response_model=LookupResponse)
async def lookup_series(term: str, request: Request) -> LookupResponse:
    """Live ComicVine volume search; no library side effect (FRG-API-003).

    NOTE on the two ``except`` arms below: ``ComicVineClient._paginate`` (which
    ``search_series`` rides) carves out ``ComicVineAuthError`` — a missing or
    invalid API key propagates out of the pagination walk rather than degrading
    to a partial/empty ``SearchResult`` (FRG-META-004) — so the auth arm below
    IS a reachable path and maps a credential failure to a 503 naming the key.
    Every OTHER per-page ``ComicVineError`` is still swallowed internally and
    degrades to ``complete=False``, so a mid-walk outage surfaces here as a 200
    envelope with ``complete=false``, not a 503; the general ``ComicVineError``
    arm is a defensive backstop against any future client change that raises
    directly."""
    settings = request.app.state.settings
    factory = comicvine_factory(settings)
    try:
        async with ComicVineClient(settings, factory) as cv:
            result = await cv.search_series(term)
    except ComicVineAuthError as exc:
        # Static message and static log line — never interpolate the key or
        # the exception's raw text, so no credential value can reach the
        # response body or the log.
        logger.warning(
            "series lookup rejected by ComicVine: API key missing or invalid"
        )
        raise ApiError(
            _COMICVINE_LOOKUP_ERROR_STATUS,
            f"comicvine lookup failed: {COMICVINE_CREDENTIAL_MESSAGE}",
            field="comicvine_api_key",
        ) from exc
    except ComicVineError as exc:
        raise ApiError(
            _COMICVINE_LOOKUP_ERROR_STATUS, f"comicvine lookup failed: {exc}"
        ) from exc

    ids = [candidate.series.cv_volume_id for candidate in result.candidates]
    have: set[int] = set()
    if ids:
        db = request.app.state.db
        async with db.read_session() as session:
            rows = await session.execute(
                select(SeriesRow.cv_volume_id).where(SeriesRow.cv_volume_id.in_(ids))
            )
            have = set(rows.scalars().all())

    return LookupResponse(
        records=[
            LookupCandidateResource(
                cv_volume_id=candidate.series.cv_volume_id,
                name=candidate.series.name,
                publisher=candidate.series.publisher,
                start_year=candidate.series.start_year,
                count_of_issues=candidate.series.count_of_issues,
                image_url=candidate.series.image_url,
                name_similarity=candidate.plausibility.name_similarity,
                year_proximity=candidate.plausibility.year_proximity,
                target_issue_plausible=candidate.plausibility.target_issue_plausible,
                have_it=candidate.series.cv_volume_id in have,
            )
            for candidate in result.candidates
        ],
        complete=result.complete,
        truncated=result.truncated,
    )


@router.get("/{series_id}", response_model=SeriesResource)
async def get_series(series_id: int, request: Request) -> SeriesResource:
    db = request.app.state.db
    async with db.read_session() as session:
        row = await repo.get_series(session, series_id)
        if row is None:
            raise ApiError(404, f"series {series_id} not found")
        stats = await repo.series_statistics(session, series_id)
    return SeriesResource.from_row_and_stats(row, stats)


@router.post("", status_code=201, response_model=SeriesCreateResponse)
async def create_series(
    body: SeriesCreate, request: Request
) -> SeriesCreateResponse:
    """Validate + persist a series, enqueue its refresh chain (FRG-API-003,
    FRG-SER-005/006). On success, the queued refresh command id rides in the
    response body alongside the created series."""
    db = request.app.state.db
    settings = request.app.state.settings
    commands = request.app.state.commands
    try:
        result = await add_series(
            db,
            settings,
            cv_volume_id=body.cv_volume_id,
            root_folder_id=body.root_folder_id,
            commands=commands,
            format_profile_id=body.format_profile_id,
            monitor_strategy=body.monitor_strategy,
            monitor_new_items=body.monitor_new_items,
            search_on_add=body.search_on_add,
            path_override=body.path,
        )
    except SeriesValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    # A just-created series has no issues/files yet (they only arrive later,
    # via the async refresh chain this call just enqueued) — the statistics
    # are deterministically zero, so skip the 4-query aggregate read
    # entirely rather than asking the DB to confirm what add_series already
    # guarantees.
    stats = SeriesStatistics(
        issue_count=0,
        file_count=0,
        missing_count=0,
        size_on_disk=0,
        next_release_date=None,
        last_release_date=None,
    )
    return SeriesCreateResponse.from_row_stats_and_command(
        result.series, stats, result.refresh_command_id
    )


@router.put("/{series_id}", response_model=SeriesResource)
async def update_series(
    series_id: int, body: SeriesEdit, request: Request
) -> SeriesResource:
    db = request.app.state.db
    try:
        row = await edit_series(
            db,
            series_id,
            monitored=body.monitored,
            monitor_new_items=body.monitor_new_items,
            format_profile_id=body.format_profile_id,
            root_folder_id=body.root_folder_id,
            path=body.path,
            aliases=body.aliases,
        )
    except SeriesNotFoundError as exc:
        raise ApiError(404, str(exc)) from exc
    except SeriesValidationError as exc:
        raise ApiError(400, str(exc)) from exc
    except OSError as exc:
        # A `path` change validated under a registered root folder but whose
        # on-disk rename then failed (permission denied, disk full,
        # cross-device link, ...). `edit_series`'s own docstring documents
        # this: the OSError propagates so the row change rolls back — but it
        # is a bare OSError, not a flow-level exception, so it still needs
        # translating into the uniform error shape here rather than
        # surfacing as an unhandled 500.
        raise ApiError(500, f"path rename failed: {exc}") from exc

    async with db.read_session() as session:
        stats = await repo.series_statistics(session, series_id)
    return SeriesResource.from_row_and_stats(row, stats)


@router.delete("/{series_id}")
async def remove_series(
    series_id: int,
    request: Request,
    response: Response,
    deleteFiles: bool = Query(False),
):
    """Delete a series (FRG-SER-014, FRG-API-003 delete-files scenario).

    Plain ``DELETE`` (no files) is bounded, synchronous work: it removes the
    rows and returns ``204``. ``?deleteFiles=true`` instead ENQUEUES a
    ``delete-series-files`` command (the manual-import precedent) and returns
    ``202`` with the ``CommandResource``: the per-file recycle moves are
    blocking syscalls that would freeze the loop for a big series on a slow
    mount if run inline, and the command shares ``IMPORT_FILE_MUTATION_GROUP``
    so a concurrent import/rescan cannot add a file after the delete snapshots
    the file list (which would orphan it). A 404 is still returned up front
    when the series does not exist, in both modes."""
    db = request.app.state.db
    settings = request.app.state.settings

    if deleteFiles:
        async with db.read_session() as session:
            if await repo.get_series(session, series_id) is None:
                raise ApiError(404, f"series {series_id} not found")
        service = request.app.state.commands
        try:
            record = await service.enqueue(
                "delete-series-files", {"series_id": series_id}
            )
        except CommandValidationError as exc:  # pragma: no cover - defensive
            raise ApiError(400, str(exc)) from exc
        response.status_code = 202
        return CommandResource.from_record(record)

    try:
        await delete_series(db, series_id, delete_files=False, settings=settings)
    except SeriesNotFoundError as exc:
        raise ApiError(404, str(exc)) from exc
    return Response(status_code=204)


@router.get("/{series_id}/cover")
async def get_series_cover(series_id: int, request: Request) -> FileResponse:
    """Serve the cached cover from disk only — no proxying, no re-fetch
    (FRG-META-013). Missing cover -> deterministic 404."""
    settings = request.app.state.settings
    cover_path = Path(settings.config_dir) / "covers" / f"{series_id}.jpg"
    if not cover_path.is_file():
        raise ApiError(404, f"no cached cover for series {series_id}")
    return FileResponse(cover_path, media_type="image/jpeg")
