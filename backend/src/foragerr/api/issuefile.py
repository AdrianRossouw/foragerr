"""Issue-file HTTP surface (FRG-API-003, FRG-UI-004, FRG-PP-013).

One route: user-initiated deletion of a single library file, riding the
existing ``delete_issue_file`` flow — the file goes through the recycle bin
when one is configured (permanent delete otherwise), the row removal returns
the issue to the derived Wanted state, and the ``file_deleted`` history event
records ``source=manual`` (a user action). No business logic lives here.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foragerr.api.errors import ApiError
from foragerr.commands.service import daemon_offload
from foragerr.library.flows import IssueFileNotFoundError, delete_issue_file

router = APIRouter(prefix="/issuefile", tags=["issuefile"])


class IssueFileDeleteResponse(BaseModel):
    """Outcome of a delete: where the file went. ``recycled`` is the recycle-
    bin destination path, or ``None`` when the file was permanently deleted
    (no bin configured) or was already absent on disk."""

    recycled: str | None


@router.delete("/{issue_file_id}", response_model=IssueFileDeleteResponse)
async def remove_issue_file(
    issue_file_id: int, request: Request
) -> IssueFileDeleteResponse:
    """Delete one library file by id (FRG-UI-004): recycle-bin routing, row
    removal (issue returns to Wanted), ``file_deleted`` event with
    ``source=manual``. Unknown id -> 404.

    Stays synchronous (a single file is bounded work), but the blocking
    filesystem move/unlink runs off the event loop through ``daemon_offload``
    so a slow mount cannot freeze the request loop. Unlike the series
    delete-files path this is NOT serialized against concurrent imports: the
    single-file race window (a rescan touching the same one file mid-delete)
    is accepted — the compensation ordering keeps the row and file consistent,
    and one file is not worth an exclusivity-group round-trip."""
    db = request.app.state.db
    settings = request.app.state.settings
    try:
        recycled = await delete_issue_file(
            db, settings, issue_file_id, offload=daemon_offload
        )
    except IssueFileNotFoundError as exc:
        raise ApiError(404, str(exc)) from exc
    return IssueFileDeleteResponse(recycled=recycled)
