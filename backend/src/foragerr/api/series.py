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

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from foragerr.api.command import CommandResource
from foragerr.api.errors import ApiError
from foragerr.api.paging import paginate
from foragerr.commands import CommandValidationError
from foragerr.library import containment, repo
from foragerr.library.booktype import COLLECTED_BOOKTYPES
from foragerr.library.flows import (
    BOOKTYPE_EDIT_ACTIONS,
    GROUP_EDIT_ACTIONS,
    MAX_ALIAS_LENGTH,
    BooktypeEdit,
    GroupEdit,
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
    ComicVineBudgetExhausted,
    ComicVineClient,
    ComicVineError,
    sanitize_cv_text,
    sort_by_relevance,
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
        "series_group_id": row.series_group_id,
        "booktype": row.booktype,
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
    #: The franchise group this series belongs to (FRG-SER-016), or ``None``
    #: when ungrouped — lets the flat view render a group affordance without a
    #: second call. Display-only; unrelated to identity/wanted state.
    series_group_id: int | None
    #: The collected-edition (trade) book-type (FRG-SER-018): ``tpb``/``gn``/
    #: ``hc``/``one_shot``, or ``None`` for an ordinary single-issues run.
    #: Display/naming metadata only — never affects wanted state (FRG-SER-019).
    booktype: str | None
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


#: The explicit-single-issues sentinel accepted in ``SeriesCreate.booktype`` —
#: distinct from an omitted field (derive as before). It maps to a persisted
#: NULL book-type with the lock set, so refresh never re-derives a trade cue
#: over the operator's "these are single issues" choice (FRG-SER-018).
_BOOKTYPE_NONE = "none"

#: Every value ``SeriesCreate.booktype`` accepts: the collected-edition
#: vocabulary (``tpb``/``gn``/``hc``/``one_shot``) plus the explicit
#: single-issues sentinel. Absent/``None`` is also valid and means "derive".
_ADD_BOOKTYPE_VALUES: tuple[str, ...] = (*COLLECTED_BOOKTYPES, _BOOKTYPE_NONE)


class SeriesCreate(BaseModel):
    """Request body for ``POST /api/v1/series`` (write-only add options)."""

    cv_volume_id: int
    root_folder_id: int
    format_profile_id: int | None = None
    monitor_strategy: str = "all"
    monitor_new_items: str = "all"
    search_on_add: bool = False
    path: str | None = None
    #: Optional add-time collected-edition book-type override (FRG-SER-005/018).
    #: A vocabulary value (``tpb``/``gn``/``hc``/``one_shot``) types the series
    #: and LOCKS it; an explicit single-issues choice — the literal ``"none"``
    #: OR an explicit JSON ``null`` — locks it as single issues (persisted
    #: NULL); *omitting* the field entirely derives the book-type from the title
    #: exactly as before. Presence is detected via ``model_fields_set`` so an
    #: explicit ``null`` is never confused with omission. An unknown value is
    #: rejected at the model boundary — surfacing (like every request-body
    #: validation failure in this app) as the uniform 400 ``{message, errors}``
    #: shape, not a bare 422.
    booktype: str | None = None

    @field_validator("booktype")
    @classmethod
    def _validate_booktype(cls, value: str | None) -> str | None:
        if value is not None and value not in _ADD_BOOKTYPE_VALUES:
            raise ValueError(
                f"invalid booktype {value!r}; expected one of "
                f"{list(_ADD_BOOKTYPE_VALUES)} or omit to derive from the title"
            )
        return value


class SeriesCreateResponse(SeriesResource):
    """The created series plus the id of the queued refresh command."""

    refresh_command_id: int

    @classmethod
    def from_row_stats_and_command(
        cls, row: SeriesRow, stats: SeriesStatistics, refresh_command_id: int
    ) -> "SeriesCreateResponse":
        return cls(**_series_fields(row, stats), refresh_command_id=refresh_command_id)


class SeriesGroupEdit(BaseModel):
    """A franchise-grouping correction (FRG-SER-017), nested in ``SeriesEdit``.

    ``action``: ``reassign`` (needs ``series_group_id``) moves the series to a
    group and LOCKS it; ``detach`` ungroups + locks it; ``rename`` (needs
    ``title``) relabels the series' current group; ``unlock`` clears the lock
    so the next refresh re-derives. Reassign/detach/rename are validated by the
    flow (unknown/missing target -> 400)."""

    action: Literal[GROUP_EDIT_ACTIONS]  # type: ignore[valid-type]
    series_group_id: int | None = None
    title: str | None = None


class SeriesBooktypeEdit(BaseModel):
    """A collected-edition book-type correction (FRG-SER-018), nested in
    ``SeriesEdit`` (mirroring the ``group`` sub-object precedent).

    ``action``: ``set`` (needs ``booktype``, one of ``tpb``/``gn``/``hc``/
    ``one_shot``) types the series and LOCKS it so refresh won't re-derive;
    ``unlock`` clears the lock so the next refresh re-derives. A bad/missing
    value for ``set`` is rejected by the flow (-> 400). Display/naming only —
    never changes wanted state (FRG-SER-019)."""

    action: Literal[BOOKTYPE_EDIT_ACTIONS]  # type: ignore[valid-type]
    booktype: str | None = None


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
    #: A single franchise-grouping correction (FRG-SER-017); ``None`` leaves
    #: the series' grouping unchanged.
    group: SeriesGroupEdit | None = None
    #: A single collected-edition book-type correction (FRG-SER-018); ``None``
    #: leaves the series' typing unchanged.
    booktype: SeriesBooktypeEdit | None = None


#: Cap on the description/deck shipped on a search/suggest candidate — the add
#: screen's result card clamps it to two lines, so ~300 chars is ample. Applied
#: at a word boundary by :func:`_candidate_description`.
_CANDIDATE_DESCRIPTION_MAX = 300


def _candidate_description(raw: str | None) -> str | None:
    """The short description ("deck") shipped on a lookup/suggest candidate.

    ComicVine volumes reach the API as :class:`SeriesRecord`\\ s whose
    ``description`` was already ingest-sanitized (``map_volume`` ->
    ``sanitize_cv_text``, FRG-META-014), but this is the API egress for
    wiki-editable text, so it re-runs :func:`sanitize_cv_text` as a defensive
    belt (idempotent on already-clean text; guarantees no raw CV HTML can ever
    leave here even if a future record path skips ingest sanitization), then
    truncates to :data:`_CANDIDATE_DESCRIPTION_MAX` chars at a word boundary
    with a trailing ellipsis. ``None`` stays ``None``.
    """
    text = sanitize_cv_text(raw)
    if text is None or len(text) <= _CANDIDATE_DESCRIPTION_MAX:
        return text
    cut = text[:_CANDIDATE_DESCRIPTION_MAX]
    head, _, _ = cut.rpartition(" ")
    return (head or cut).rstrip() + "…"


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
    #: Sanitized, word-boundary-truncated short description for the result
    #: card's two-line deck (FRG-META-007/014, via
    #: :func:`_candidate_description`); ``None`` when ComicVine has none.
    description: str | None
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


class SuggestCandidateResource(BaseModel):
    """One bounded ComicVine suggest candidate (FRG-API-017) — deliberately
    NARROWER than :class:`LookupCandidateResource`: no plausibility signals
    (``name_similarity``/``year_proximity``/``target_issue_plausible``),
    since suggest skips that scoring to stay cheap. ``have_it`` is still
    computed over the ≤10 returned ids for parity with the full lookup, and
    ``description`` ships the same sanitized/truncated deck the lookup
    candidate carries so both result-card renderings agree."""

    cv_volume_id: int
    name: str | None
    publisher: str | None
    start_year: int | None
    count_of_issues: int | None
    image_url: str | None
    #: Same sanitized, word-boundary-truncated deck as the lookup candidate
    #: (FRG-META-007/014, via :func:`_candidate_description`).
    description: str | None
    have_it: bool


class SuggestResponse(BaseModel):
    """Suggest outcome envelope (FRG-API-017). Carries ``complete`` (a clean
    single-page fetch vs. one degraded by a mid-fetch upstream failure) but
    deliberately has NO ``truncated`` field, unlike :class:`LookupResponse`:
    a suggest result is definitionally partial — the full ``GET /lookup``
    remains the complete search — so a cap is not a truncation to signal."""

    records: list[SuggestCandidateResource]
    complete: bool


class GroupedSeriesResource(BaseModel):
    """A minimal member-series view nested under a franchise header
    (FRG-API-020) — enough to render a row and navigate, deliberately WITHOUT
    per-series statistics (those would reintroduce the N+1 the group roll-up
    exists to avoid; the flat ``GET /series`` carries full stats)."""

    id: int
    cv_volume_id: int
    title: str
    sort_title: str
    status: str
    start_year: int | None
    monitored: bool
    series_group_id: int | None

    @classmethod
    def from_row(cls, row: SeriesRow) -> "GroupedSeriesResource":
        return cls(
            id=row.id,
            cv_volume_id=row.cv_volume_id,
            title=row.title,
            sort_title=row.sort_title,
            status=row.status,
            start_year=row.start_year,
            monitored=row.monitored,
            series_group_id=row.series_group_id,
        )


class SeriesGroupResource(BaseModel):
    """One franchise in the grouped view (FRG-API-020): a real group, or an
    ungrouped series as its own franchise of one.

    ``id`` is the group id, or ``None`` for a singleton (ungrouped) franchise;
    ``kind`` disambiguates (``"group"`` / ``"series"``). The counts are the
    aggregated roll-up from a bounded query — never per-series stats per
    group. ``series`` nests the member rows (one, for a singleton)."""

    id: int | None
    kind: str
    title: str
    series_count: int
    issue_count: int
    owned_count: int
    series: list[GroupedSeriesResource]


class SeriesGroupPage(BaseModel):
    """Paging envelope (FRG-API-006) specialized for franchise groups."""

    page: int
    pageSize: int
    sortKey: str
    sortDirection: str
    totalRecords: int
    records: list[SeriesGroupResource]


class CollectionRangeResource(BaseModel):
    """One declared sub-range within a collections rollup entry (FRG-API-022).

    ``start_issue_id``/``end_issue_id`` are the target series' issues currently
    at the stored ordering-key bounds (``null`` when no surviving issue has that
    exact key) — the edit dialog pre-fills its endpoint pickers from them."""

    target_series_id: int
    label: str
    start_issue_id: int | None
    end_issue_id: int | None


class CollectionRecordResource(BaseModel):
    """One collected book that declares a range targeting this series
    (FRG-API-022), with request-time singles-coverage.

    ``coverage`` is ``collected`` when every issue in every declared range has
    a file, ``partial`` when some do, ``none`` when none do (or the ranges
    cover no issues) — computed read-only, never persisted."""

    trade_issue_id: int
    trade_series_id: int
    trade_series_title: str
    booktype: str | None
    release_date: dt.date | None
    ranges: list[CollectionRangeResource]
    coverage: str
    issues_in_ranges: int
    owned_in_ranges: int

    @classmethod
    def from_rollup(
        cls, rollup: "containment.CollectionRollup"
    ) -> "CollectionRecordResource":
        return cls(
            trade_issue_id=rollup.trade_issue_id,
            trade_series_id=rollup.trade_series_id,
            trade_series_title=rollup.trade_series_title,
            booktype=rollup.booktype,
            release_date=rollup.release_date,
            ranges=[
                CollectionRangeResource(
                    target_series_id=r.target_series_id,
                    label=r.label,
                    start_issue_id=r.start_issue_id,
                    end_issue_id=r.end_issue_id,
                )
                for r in rollup.ranges
            ],
            coverage=rollup.coverage,
            issues_in_ranges=rollup.issues_in_ranges,
            owned_in_ranges=rollup.owned_in_ranges,
        )


class CollectionsResponse(BaseModel):
    """The collections resource for a series (FRG-API-022): containment BOTH
    directions touch — the collected books that declare a range targeting it
    and, when the series is itself trade-typed, its own issues' declarations."""

    records: list[CollectionRecordResource]


#: Whitelisted sort keys for the grouped projection (FRG-API-006). The
#: projection is composed in-process (groups + singletons from bounded
#: aggregate queries), so these map to resource attributes, not SQL columns.
_GROUP_SORT_KEYS = ("title", "issue_count", "owned_count", "series_count")


# --- routes -------------------------------------------------------------------


def _comicvine_error_to_api_error(exc: ComicVineError) -> ApiError:
    """Map any ComicVine client failure to the uniform error the lookup
    FAMILY surfaces — shared verbatim by ``GET /lookup`` (FRG-API-003) and
    ``GET /lookup/suggest`` (FRG-API-017) so neither route carries a parallel
    copy of this mapping and the frontend's ``isComicVineAuthError`` sniff
    classifies a suggest 503 identically to a lookup 503.

    ``ComicVineAuthError`` (a missing/invalid key propagating out of the
    client rather than degrading to a partial/empty result — see
    ``ComicVineClient._paginate``'s and ``suggest_series``'s auth carve-outs)
    maps to the dedicated credential message plus the machine-readable
    ``field="comicvine_api_key"`` discriminator, and logs ONE static warning
    naming the failure — never the key value. Every other ``ComicVineError``
    is a defensive backstop mapped to a generic 503 naming the failure."""
    if isinstance(exc, ComicVineAuthError):
        # Static message and static log line — never interpolate the key or
        # the exception's raw text, so no credential value can reach the
        # response body or the log.
        logger.warning(
            "series lookup rejected by ComicVine: API key missing or invalid"
        )
        return ApiError(
            _COMICVINE_LOOKUP_ERROR_STATUS,
            f"comicvine lookup failed: {COMICVINE_CREDENTIAL_MESSAGE}",
            field="comicvine_api_key",
        )
    if isinstance(exc, ComicVineBudgetExhausted):
        # An honest, user-legible deferral message with the resume time
        # (FRG-META-016) — no key material, only the bucket + a duration. Mapped
        # to the same 503 the lookup family uses; the frontend surfaces the
        # message through its existing lookup-error path.
        minutes = max(1, round(exc.retry_after_seconds / 60))
        return ApiError(
            _COMICVINE_LOOKUP_ERROR_STATUS,
            "ComicVine hourly request budget exhausted for this lookup; "
            f"retries in about {minutes} minute(s).",
        )
    return ApiError(
        _COMICVINE_LOOKUP_ERROR_STATUS, f"comicvine lookup failed: {exc}"
    )


@router.get("", response_model=SeriesPage)
async def list_series(
    request: Request,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortKey: str = Query("sort_title"),
    sortDirection: str = Query("asc"),
    collected: bool | None = Query(None),
) -> SeriesPage:
    """Paged series index with nested statistics (FRG-API-003, FRG-API-006).

    ``repo.series_statistics()`` runs several small aggregate queries per
    row (issue count, file count/size, next/last release date) — a known
    N+1 across the page (up to ~4 * pageSize queries), acceptable at M1
    scale (int aggregates over indexed FKs, no heavy joins) but NOT free;
    not fixed here (see the API-area report for rationale).

    ``collected`` (FRG-SER-018) optionally partitions by collected-edition
    typing: ``true`` -> only typed (``booktype IS NOT NULL``) series, ``false``
    -> only single-issues (``booktype IS NULL``) series, absent -> no filter.
    A display filter only; it composes with sort/paging and never touches
    wanted state (FRG-SER-019)."""
    db = request.app.state.db
    stmt = select(SeriesRow)
    if collected is True:
        stmt = stmt.where(SeriesRow.booktype.is_not(None))
    elif collected is False:
        stmt = stmt.where(SeriesRow.booktype.is_(None))
    async with db.read_session() as session:
        result = await paginate(
            session,
            stmt=stmt,
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


# NOTE: registered BEFORE "/{series_id}" (like "/lookup") so "groups" is never
# swallowed by the int-typed path parameter.
@router.get("/groups", response_model=SeriesGroupPage)
async def list_series_groups(
    request: Request,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortKey: str = Query("title"),
    sortDirection: str = Query("asc"),
) -> SeriesGroupPage:
    """The grouped-library read projection (FRG-API-020).

    Franchise groups (each with member series and an AGGREGATED roll-up) plus
    every ungrouped series as its own franchise of one. The roll-up counts
    come from bounded aggregate queries (``repo.series_group_rollup`` /
    ``ungrouped_series_rollup``) — NOT the per-series ``series_statistics``
    path multiplied per group (no N+1). Read-only; exposes no secret. Standard
    paging envelope; the franchise list is composed and paged in-process."""
    if sortDirection not in ("asc", "desc"):
        raise ApiError(
            400,
            f"sortDirection must be one of ('asc', 'desc') (got {sortDirection!r})",
            field="sortDirection",
        )
    if sortKey not in _GROUP_SORT_KEYS:
        raise ApiError(
            400,
            f"unknown sortKey {sortKey!r}; must be one of {sorted(_GROUP_SORT_KEYS)}",
            field="sortKey",
        )

    db = request.app.state.db
    async with db.read_session() as session:
        rollups = await repo.series_group_rollup(session)
        grouped_members = await repo.list_grouped_series(session)
        ungrouped_stats = await repo.ungrouped_series_rollup(session)
        ungrouped = await repo.list_ungrouped_series(session)

    members_by_group: dict[int, list[SeriesRow]] = {}
    for member in grouped_members:
        members_by_group.setdefault(member.series_group_id, []).append(member)

    franchises: list[SeriesGroupResource] = []
    for rollup in rollups:
        franchises.append(
            SeriesGroupResource(
                id=rollup.group_id,
                kind="group",
                title=rollup.title,
                series_count=rollup.series_count,
                issue_count=rollup.issue_count,
                owned_count=rollup.owned_count,
                series=[
                    GroupedSeriesResource.from_row(m)
                    for m in members_by_group.get(rollup.group_id, [])
                ],
            )
        )
    for series in ungrouped:
        stats = ungrouped_stats.get(series.id)
        franchises.append(
            SeriesGroupResource(
                id=None,
                kind="series",
                title=series.title,
                series_count=1,
                issue_count=stats.issue_count if stats else 0,
                owned_count=stats.owned_count if stats else 0,
                series=[GroupedSeriesResource.from_row(series)],
            )
        )

    reverse = sortDirection == "desc"
    if sortKey == "title":
        franchises.sort(key=lambda f: f.title.casefold(), reverse=reverse)
    else:
        franchises.sort(key=lambda f: getattr(f, sortKey), reverse=reverse)

    total = len(franchises)
    start = (page - 1) * pageSize
    window = franchises[start : start + pageSize]
    return SeriesGroupPage(
        page=page,
        pageSize=pageSize,
        sortKey=sortKey,
        sortDirection=sortDirection,
        totalRecords=total,
        records=window,
    )


# NOTE: registered BEFORE "/{series_id}" so "lookup" is never swallowed by
# the int-typed path parameter.
@router.get("/lookup", response_model=LookupResponse)
async def lookup_series(term: str, request: Request) -> LookupResponse:
    """Live ComicVine volume search; no library side effect (FRG-API-003).

    NOTE on the single ``except`` arm below: ``ComicVineClient._paginate``
    (which ``search_series`` rides) carves out ``ComicVineAuthError`` — a
    missing or invalid API key propagates out of the pagination walk rather
    than degrading to a partial/empty ``SearchResult`` (FRG-META-004) — so
    ``_comicvine_error_to_api_error`` (shared verbatim with the
    ``/lookup/suggest`` route, FRG-API-017) IS reached for a credential
    failure and maps it to a 503 naming the key. Every OTHER per-page
    ``ComicVineError`` is still swallowed internally and degrades to
    ``complete=False``, so a mid-walk outage surfaces here as a 200 envelope
    with ``complete=false``, not a 503; catching the general
    ``ComicVineError`` here (which also matches its ``ComicVineAuthError``
    subclass) is a defensive backstop against any future client change that
    raises directly."""
    settings = request.app.state.settings
    factory = comicvine_factory(settings)
    try:
        async with ComicVineClient(settings, factory) as cv:
            result = await cv.search_series(term)
    except ComicVineError as exc:
        raise _comicvine_error_to_api_error(exc) from exc

    # Relevance ordering happens here, after annotation, sharing one sort
    # function with the suggest route so the two never drift (FRG-META-015).
    candidates = sort_by_relevance(
        term, result.candidates, record_of=lambda candidate: candidate.series
    )

    ids = [candidate.series.cv_volume_id for candidate in candidates]
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
                description=_candidate_description(candidate.series.description),
                name_similarity=candidate.plausibility.name_similarity,
                year_proximity=candidate.plausibility.year_proximity,
                target_issue_plausible=candidate.plausibility.target_issue_plausible,
                have_it=candidate.series.cv_volume_id in have,
            )
            for candidate in candidates
        ],
        complete=result.complete,
        truncated=result.truncated,
    )


# NOTE: registered BEFORE "/{series_id}" (like "/lookup" above) so
# "lookup/suggest" is never swallowed by the int-typed path parameter.
@router.get("/lookup/suggest", response_model=SuggestResponse)
async def suggest_series(term: str, request: Request) -> SuggestResponse:
    """Bounded, first-page-only ComicVine suggestion for as-you-type UX
    (FRG-API-017) — a cheap accelerator over ``GET /lookup``, riding
    ``ComicVineClient.suggest_series`` which fetches a single page and NEVER
    performs the full pagination walk ``search_series`` does. Reuses
    ``GET /lookup``'s error mapping verbatim via
    ``_comicvine_error_to_api_error`` (see that route's docstring for why the
    single ``except ComicVineError`` arm below still reaches the auth-specific
    503 for a credential failure), so the frontend's ``isComicVineAuthError``
    classifies a suggest 503 identically to a lookup 503. No plausibility
    scoring is computed (see ``SuggestCandidateResource``); ``have_it`` is
    still annotated over the ≤10 returned ids."""
    settings = request.app.state.settings
    factory = comicvine_factory(settings)
    try:
        async with ComicVineClient(settings, factory) as cv:
            result = await cv.suggest_series(term)
    except ComicVineError as exc:
        raise _comicvine_error_to_api_error(exc) from exc

    # Same relevance ordering as GET /lookup, sharing one sort function so the
    # candidates the two endpoints have in common appear in the same relative
    # order (FRG-META-015). Suggest candidates are bare records, so the identity
    # extractor feeds them straight in.
    candidates = sort_by_relevance(
        term, result.candidates, record_of=lambda record: record
    )

    ids = [record.cv_volume_id for record in candidates]
    have: set[int] = set()
    if ids:
        db = request.app.state.db
        async with db.read_session() as session:
            rows = await session.execute(
                select(SeriesRow.cv_volume_id).where(SeriesRow.cv_volume_id.in_(ids))
            )
            have = set(rows.scalars().all())

    return SuggestResponse(
        records=[
            SuggestCandidateResource(
                cv_volume_id=record.cv_volume_id,
                name=record.name,
                publisher=record.publisher,
                start_year=record.start_year,
                count_of_issues=record.count_of_issues,
                image_url=record.image_url,
                description=_candidate_description(record.description),
                have_it=record.cv_volume_id in have,
            )
            for record in candidates
        ],
        complete=result.complete,
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
    # Resolve the optional add-time book-type override into the two row-shaped
    # arguments the add flow takes (FRG-SER-005/018). The field was already
    # vocabulary-validated on the model (bad value -> 400). Presence is read from
    # ``model_fields_set`` — NOT from ``body.booktype is not None`` — so an
    # explicit single-issues choice sent as JSON ``null`` locks a NULL book-type
    # just like the ``"none"`` sentinel, and only an *omitted* field derives from
    # the title. (Conflating null with omission would silently drop the lock.)
    booktype_override_present = "booktype" in body.model_fields_set
    booktype_value = (
        None if body.booktype in (None, _BOOKTYPE_NONE) else body.booktype
    )
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
            booktype=booktype_value,
            booktype_locked=booktype_override_present,
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
    group_op = (
        GroupEdit(
            action=body.group.action,
            series_group_id=body.group.series_group_id,
            title=body.group.title,
        )
        if body.group is not None
        else None
    )
    booktype_op = (
        BooktypeEdit(action=body.booktype.action, booktype=body.booktype.booktype)
        if body.booktype is not None
        else None
    )
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
            group_op=group_op,
            booktype_op=booktype_op,
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


@router.get("/{series_id}/collections", response_model=CollectionsResponse)
async def list_series_collections(
    series_id: int, request: Request
) -> CollectionsResponse:
    """Containment for this series in BOTH directions (FRG-API-022): the
    collected books declaring a range targeting it and, when it is itself
    trade-typed, its own issues' declared contents — each with range labels
    (plus resolved endpoint issue ids), release date, and a request-time
    singles-coverage status (``collected``/``partial``/``none``). Read-only —
    the rollup is computed from bounded queries and touches no wanted/stats
    state (FRG-SER-020). A missing series yields a 404."""
    db = request.app.state.db
    async with db.read_session() as session:
        if await repo.get_series(session, series_id) is None:
            raise ApiError(404, f"series {series_id} not found")
        rollups = await containment.collections_for_series(session, series_id)
    return CollectionsResponse(
        records=[CollectionRecordResource.from_rollup(r) for r in rollups]
    )
