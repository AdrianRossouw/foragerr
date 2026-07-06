"""Library-import endpoints (FRG-IMP-023 API surface).

The review loop around the persisted library-import staging
(m2-existing-library-import design decision 6, following the manual-import
pattern):

- ``POST /api/v1/library-import/scan`` ``{rootFolderId}`` — enqueue a
  ``library-import-scan`` command for one registered root folder; ``201`` with
  a ``CommandResource`` (WS command-status invalidation drives the UI).
- ``GET /api/v1/library-import?rootFolderId=`` — the root's staged groups as a
  paged envelope (FRG-API-002 helper, whitelisted sort keys).
- ``PATCH /api/v1/library-import/groups/{id}`` — confirm the proposal, override
  the ComicVine volume (validated live via ``get_volume`` exactly like add), or
  skip/unskip the group.
- ``POST /api/v1/library-import/execute`` ``{groupIds, addOptions}`` — enqueue
  the ``library-import`` bulk import for confirmed groups; ``201`` with a
  ``CommandResource``.

Path safety (FRG-SEC-004): user input is only ever a ``rootFolderId`` /
``groupId`` / ``cvVolumeId`` — no endpoint accepts a filesystem path, so no new
path-confinement surface exists. Staged folder/file paths are server-derived
from the configured root's walk and echoed for display only.
"""

from __future__ import annotations

import datetime as dt
import os

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from foragerr.api.command import CommandResource
from foragerr.api.errors import ApiError
from foragerr.api.paging import envelope, paginate
from foragerr.commands import CommandValidationError
from foragerr.library.flows import decode_group_files
from foragerr.library.flows._common import (
    MONITOR_STRATEGIES,
    comicvine_factory,
)
from foragerr.library.models import LibraryImportGroupRow, RootFolderRow
from foragerr.metadata import ComicVineAuthError, ComicVineClient, ComicVineError
from foragerr.quality.models import FormatProfileRow

router = APIRouter(prefix="/library-import", tags=["library-import"])

#: Whitelisted sort keys -> fixed column expressions (FRG-API-002); the
#: client-supplied sortKey string is never interpolated into SQL.
_SORT_WHITELIST = {
    "matching_key": LibraryImportGroupRow.matching_key,
    "confidence": LibraryImportGroupRow.confidence,
    "state": LibraryImportGroupRow.state,
    "scanned_at": LibraryImportGroupRow.scanned_at,
}

#: PATCH-assignable states. ``confirmed`` requires a resolvable volume;
#: ``skipped`` deselects; ``proposed`` un-skips / un-confirms back to review.
_PATCHABLE_STATES = ("confirmed", "skipped", "proposed")


class LibraryImportFile(BaseModel):
    """One staged file of a group (server-derived; display only)."""

    path: str
    name: str
    size: int


class LibraryImportGroupResource(BaseModel):
    """One staged library-import group (FRG-IMP-023)."""

    id: int
    rootFolderId: int
    matchingKey: str
    folder: str
    files: list[LibraryImportFile]
    confidence: float
    proposedCvVolumeId: int | None
    confirmedCvVolumeId: int | None
    state: str
    message: str | None
    scannedAt: dt.datetime

    @classmethod
    def from_row(cls, row: LibraryImportGroupRow) -> "LibraryImportGroupResource":
        return cls(
            id=row.id,
            rootFolderId=row.root_folder_id,
            matchingKey=row.matching_key,
            folder=row.folder,
            files=[
                LibraryImportFile(path=path, name=os.path.basename(path), size=size)
                for path, size in decode_group_files(row.files)
            ],
            confidence=row.confidence,
            proposedCvVolumeId=row.proposed_cv_volume_id,
            confirmedCvVolumeId=row.confirmed_cv_volume_id,
            state=row.state,
            message=row.message,
            scannedAt=row.scanned_at,
        )


class ScanRequest(BaseModel):
    """Request body for ``POST /api/v1/library-import/scan``."""

    rootFolderId: int


class GroupPatch(BaseModel):
    """Request body for ``PATCH /api/v1/library-import/groups/{id}``.

    ``cvVolumeId`` overrides the match (validated live against ComicVine, like
    add) and implies confirmation; ``state`` alone confirms the existing
    proposal, skips, or returns the group to review.
    """

    state: str | None = None
    cvVolumeId: int | None = None


class AddOptionsBody(BaseModel):
    """Batch add options applied to every series the execute run creates."""

    formatProfileId: int | None = None
    monitorStrategy: str = "all"
    searchOnAdd: bool = False


class ExecuteRequest(BaseModel):
    """Request body for ``POST /api/v1/library-import/execute``."""

    groupIds: list[int]
    addOptions: AddOptionsBody = AddOptionsBody()


async def _require_root(session, root_folder_id: int) -> RootFolderRow:
    root = await session.get(RootFolderRow, root_folder_id)
    if root is None:
        raise ApiError(
            404,
            f"root folder {root_folder_id} is not registered",
            field="rootFolderId",
        )
    return root


@router.post("/scan", status_code=201, response_model=CommandResource)
async def scan_endpoint(body: ScanRequest, request: Request) -> CommandResource:
    """Enqueue a staging scan of one registered root folder (FRG-IMP-023)."""
    db = request.app.state.db
    service = request.app.state.commands
    async with db.read_session() as session:
        await _require_root(session, body.rootFolderId)
    try:
        record = await service.enqueue(
            "library-import-scan", {"root_folder_id": body.rootFolderId}
        )
    except CommandValidationError as exc:  # pragma: no cover - schema-valid here
        raise ApiError(400, str(exc)) from exc
    return CommandResource.from_record(record)


@router.get("")
async def list_groups_endpoint(
    request: Request,
    rootFolderId: int = Query(...),
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
    sortKey: str = Query("matching_key"),
    sortDirection: str = Query("asc"),
) -> dict:
    """The root's staged groups as a paged envelope (FRG-API-002 shape)."""
    db = request.app.state.db
    async with db.read_session() as session:
        await _require_root(session, rootFolderId)
        result = await paginate(
            session,
            stmt=select(LibraryImportGroupRow).where(
                LibraryImportGroupRow.root_folder_id == rootFolderId
            ),
            page=page,
            page_size=pageSize,
            sort_key=sortKey,
            sort_direction=sortDirection,
            whitelist=_SORT_WHITELIST,
        )
    return envelope(
        page=result["page"],
        page_size=result["pageSize"],
        sort_key=result["sortKey"],
        sort_direction=result["sortDirection"],
        total_records=result["totalRecords"],
        records=[
            LibraryImportGroupResource.from_row(row).model_dump()
            for row in result["records"]
        ],
    )


async def _validate_cv_volume(request: Request, cv_volume_id: int) -> None:
    """Validate an override volume live against ComicVine, like add does.

    An unknown/unfetchable volume is a 400 naming the id; a credential failure
    is a 503 with the static wording (no key material leaks)."""
    settings = request.app.state.settings
    factory = comicvine_factory(settings)
    try:
        async with ComicVineClient(settings, factory) as cv:
            await cv.get_volume(cv_volume_id)
    except ComicVineAuthError as exc:
        raise ApiError(
            503,
            "ComicVine rejected the API key (missing or invalid) — "
            "set comicvine_api_key",
        ) from exc
    except ComicVineError as exc:
        raise ApiError(
            400,
            f"comicvine volume {cv_volume_id} could not be fetched: {exc}",
            field="cvVolumeId",
        ) from exc


@router.patch("/groups/{group_id}", response_model=LibraryImportGroupResource)
async def patch_group_endpoint(
    group_id: int, body: GroupPatch, request: Request
) -> LibraryImportGroupResource:
    """Confirm / override / skip one staged group (FRG-IMP-023)."""
    db = request.app.state.db
    if body.state is None and body.cvVolumeId is None:
        raise ApiError(400, "supply state and/or cvVolumeId", field="state")
    if body.state is not None and body.state not in _PATCHABLE_STATES:
        raise ApiError(
            400,
            f"state must be one of {list(_PATCHABLE_STATES)} (got {body.state!r})",
            field="state",
        )

    # Live ComicVine validation happens OUTSIDE the write lock (network I/O).
    if body.cvVolumeId is not None:
        await _validate_cv_volume(request, body.cvVolumeId)

    async with db.write_session() as session:
        group = await session.get(LibraryImportGroupRow, group_id)
        if group is None:
            raise ApiError(404, f"no library-import group with id {group_id}")
        if body.cvVolumeId is not None:
            group.confirmed_cv_volume_id = body.cvVolumeId
            group.state = body.state or "confirmed"
            group.message = None
        elif body.state == "confirmed":
            volume_id = group.confirmed_cv_volume_id or group.proposed_cv_volume_id
            if volume_id is None:
                raise ApiError(
                    400,
                    "group has no proposed match to confirm; "
                    "supply cvVolumeId to set one",
                    field="cvVolumeId",
                )
            group.confirmed_cv_volume_id = volume_id
            group.state = "confirmed"
            group.message = None
        elif body.state == "skipped":
            group.state = "skipped"
        else:  # "proposed": back to review
            group.state = "proposed"
            group.confirmed_cv_volume_id = None
        await session.flush()
        return LibraryImportGroupResource.from_row(group)


@router.post("/execute", status_code=201, response_model=CommandResource)
async def execute_endpoint(body: ExecuteRequest, request: Request) -> CommandResource:
    """Validate the selection and enqueue the bulk library import."""
    db = request.app.state.db
    service = request.app.state.commands
    if not body.groupIds:
        raise ApiError(400, "no groups selected for import", field="groupIds")
    if body.addOptions.monitorStrategy not in MONITOR_STRATEGIES:
        raise ApiError(
            400,
            f"invalid monitor strategy {body.addOptions.monitorStrategy!r}; "
            f"expected one of {list(MONITOR_STRATEGIES)}",
            field="addOptions.monitorStrategy",
        )

    async with db.read_session() as session:
        if body.addOptions.formatProfileId is not None:
            profile = await session.get(
                FormatProfileRow, body.addOptions.formatProfileId
            )
            if profile is None:
                raise ApiError(
                    400,
                    f"format profile {body.addOptions.formatProfileId} "
                    "does not exist",
                    field="addOptions.formatProfileId",
                )
        rows = (
            (
                await session.execute(
                    select(LibraryImportGroupRow).where(
                        LibraryImportGroupRow.id.in_(body.groupIds)
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {row.id: row for row in rows}
        for group_id in body.groupIds:
            group = by_id.get(group_id)
            if group is None:
                raise ApiError(
                    404, f"no library-import group with id {group_id}"
                )
            if group.state != "confirmed" or group.confirmed_cv_volume_id is None:
                raise ApiError(
                    400,
                    f"group {group_id} is not confirmed "
                    f"(state {group.state!r}); confirm or override it first",
                    field="groupIds",
                )

    try:
        record = await service.enqueue(
            "library-import",
            {
                "group_ids": body.groupIds,
                "format_profile_id": body.addOptions.formatProfileId,
                "monitor_strategy": body.addOptions.monitorStrategy,
                "search_on_add": body.addOptions.searchOnAdd,
            },
        )
    except CommandValidationError as exc:  # pragma: no cover - schema-valid here
        raise ApiError(400, str(exc)) from exc
    return CommandResource.from_record(record)
