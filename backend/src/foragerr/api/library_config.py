"""Read-only library-configuration lists for the add-series flow.

Two small GET collections the add-series screen (FRG-UI-005) reads to populate
its Root Folder and Format Profile pickers, rather than making the user type
raw ids:

- ``GET /api/v1/rootfolder`` — configured library root folders with free space
  when it can be read cheaply (FRG-SER-008).
- ``GET /api/v1/formatprofile`` — the seeded/managed format profiles
  (FRG-QUAL-001; the entity these list, served read-only for the add flow).

Both are plain arrays (no paging envelope): the sets are tiny and unbounded
growth is not a concern here. No mutation surface lives here — root-folder and
profile management are separate concerns (out of M1 scope for this change).
"""

from __future__ import annotations

import shutil

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from foragerr.library import repo
from foragerr.quality.models import FormatProfileRow, decode_formats

router = APIRouter(tags=["config"])


class RootFolderResource(BaseModel):
    """A configured library root folder (FRG-SER-008).

    ``free_space`` is the filesystem's free bytes when it can be read cheaply
    (a single ``statvfs``); ``None`` when the path is missing or unreadable —
    a stat failure never fails the list."""

    id: int
    path: str
    free_space: int | None


class FormatProfileResource(BaseModel):
    """A format profile: an ordered format ladder plus a cutoff (FRG-QUAL-001)."""

    id: int
    name: str
    formats: list[str]
    cutoff: str


@router.get("/rootfolder", response_model=list[RootFolderResource])
async def list_root_folders_endpoint(request: Request) -> list[RootFolderResource]:
    """List configured root folders with free space where cheap (FRG-SER-008)."""
    db = request.app.state.db
    async with db.read_session() as session:
        rows = await repo.list_root_folders(session)
    return [
        RootFolderResource(
            id=row.id, path=row.path, free_space=await _free_space(row.path)
        )
        for row in rows
    ]


@router.get("/formatprofile", response_model=list[FormatProfileResource])
async def list_format_profiles_endpoint(
    request: Request,
) -> list[FormatProfileResource]:
    """List every format profile, ordered by id (FRG-QUAL-001).

    Read-only: serves the add-series picker (FRG-UI-005). The seeded default
    (id 1) is always present (FRG-QUAL-002)."""
    db = request.app.state.db
    async with db.read_session() as session:
        rows = (
            (await session.execute(select(FormatProfileRow).order_by(FormatProfileRow.id)))
            .scalars()
            .all()
        )
    return [
        FormatProfileResource(
            id=row.id,
            name=row.name,
            formats=decode_formats(row.formats),
            cutoff=row.cutoff,
        )
        for row in rows
    ]


async def _free_space(path: str) -> int | None:
    """Free bytes on the filesystem holding ``path``, or ``None`` if it cannot
    be stat'd (missing mount, permission). Never raises — a stat failure must
    not fail the whole list.

    The ``disk_usage`` syscall is a BLOCKING stat that a hung network mount can
    stall on indefinitely, so it runs in the thread pool: one wedged root folder
    must never freeze the event loop and every other request with it."""
    try:
        usage = await run_in_threadpool(shutil.disk_usage, path)
    except OSError:
        return None
    return usage.free
