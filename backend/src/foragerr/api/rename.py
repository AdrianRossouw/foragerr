"""Rename preview + execute endpoints (FRG-PP-012, FRG-API-013 sibling).

``GET /api/v1/rename?seriesId=`` returns the existing→new path diffs a rename
would apply under the current templates, computed without touching disk. Execution
is an explicit second step: ``POST /api/v1/rename`` enqueues the file-mutating
``rename-series`` command onto the backbone (the same ``pp``-pool, exclusivity-
guarded transport every other library-mutating flow uses), so the preview→confirm
UI flow never mutates the library until the operator confirms.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from foragerr.api.command import CommandResource
from foragerr.library.flows.rename import preview_series_renames

router = APIRouter(tags=["rename"])


class RenamePreviewEntry(BaseModel):
    """One file's proposed rename (only files that would actually change)."""

    issueFileId: int
    issueId: int
    existingPath: str
    newPath: str


class RenameExecuteRequest(BaseModel):
    """Request body for ``POST /api/v1/rename``."""

    seriesId: int


@router.get("/rename", response_model=list[RenamePreviewEntry])
async def preview_renames_endpoint(
    request: Request, seriesId: int = Query(...)
) -> list[RenamePreviewEntry]:
    """Preview the renames a series would undergo (FRG-PP-012). Touches no disk."""
    db = request.app.state.db
    settings = request.app.state.settings
    plan = await preview_series_renames(db, settings, seriesId)
    return [
        RenamePreviewEntry(
            issueFileId=entry.issue_file_id,
            issueId=entry.issue_id,
            existingPath=entry.current_path,
            newPath=entry.new_path,
        )
        for entry in plan.changed
    ]


@router.post("/rename", status_code=201, response_model=CommandResource)
async def execute_renames_endpoint(
    body: RenameExecuteRequest, request: Request
) -> CommandResource:
    """Enqueue the rename-series command that applies the previewed renames."""
    service = request.app.state.commands
    record = await service.enqueue("rename-series", {"series_id": body.seriesId})
    return CommandResource.from_record(record)
