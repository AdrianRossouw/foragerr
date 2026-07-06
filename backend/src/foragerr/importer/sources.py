"""Import sources — the two M1 intakes as data (FRG-PP-001).

The pipeline runs one set of stages; the *source* is data, not a code fork
(design decision 1). Each source knows only how to enumerate candidate files
(its ``gather``); everything downstream (aggregate → decide → execute) is
identical and source-agnostic, keyed off the neutral :class:`ImportCandidate`.

- :class:`CompletedDownloadSource` — a completed tracked download awaiting import
  (``import_pending``). Its ``gather`` applies the client's remote-path mapping
  (FRG-PP-008), enumerates archive files under the mapped output path, and
  attaches the download id, the client item title, and the grab record's release
  title (looked up once by download id, FRG-PP-003) to each candidate.
- :class:`RescanSource` — a series-path walk (FRG-SER-010's file-routing half).
  Its ``gather`` walks the series folder to a bounded depth, skips files already
  linked to an issue, and scopes each candidate to the series.

A source never mutates the database or the tracked-download state machine — the
flows commands own those transitions. ``gather`` only reads.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.downloads.models import GrabHistoryRow
from foragerr.downloads.pathmap import RemotePathMapping, apply_mappings
from foragerr.importer.context import ImportContext
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow

# Source-kind discriminators carried on the candidate (data, not a type switch).
SOURCE_DOWNLOAD = "download"
SOURCE_RESCAN = "rescan"


@dataclass(frozen=True, slots=True)
class ImportCandidate:
    """One file to run through the pipeline, plus its aggregation evidence and
    reconciliation hints — the neutral unit both sources produce (FRG-PP-001)."""

    source_kind: str
    local_path: str
    size: int
    file_name: str
    folder_name: str | None = None
    #: Directory under which emptied dirs may be cleaned after a move (the
    #: download staging root or the series root); cleanup never crosses it.
    container_root: str | None = None
    download_id: str | None = None
    client_title: str | None = None
    grab_title: str | None = None
    #: Reconciliation hints from grab history (FRG-PP-003); may be ``None``.
    grab_series_id: int | None = None
    grab_issue_id: int | None = None
    #: Rescan pins the series scope; ``None`` for downloads (open mapping).
    series_scope_id: int | None = None
    #: Non-``None`` when the client path could not be mapped (FRG-PP-008); the
    #: pipeline turns this into an import_blocked with a mapping-fix reason.
    mapping_warning: str | None = None


def _iter_archive_files(
    root: str, extensions: tuple[str, ...], max_depth: int
) -> list[tuple[str, int]]:
    """Yield ``(path, size)`` for archive files under ``root`` to a bounded depth.

    A single regular file passed as ``root`` yields just itself. A non-existent
    path yields nothing. Depth is measured from ``root`` (0 = files directly in
    ``root``)."""
    base = Path(root)
    if base.is_file():
        try:
            return [(str(base), base.stat().st_size)]
        except OSError:
            return []
    if not base.exists():
        return []
    exts = {e.lower().lstrip(".") for e in extensions}
    out: list[tuple[str, int]] = []
    base_depth = str(base).rstrip(os.sep).count(os.sep)
    for dirpath, dirs, files in os.walk(base):
        depth = dirpath.rstrip(os.sep).count(os.sep) - base_depth
        if depth >= max_depth:
            dirs[:] = []  # do not descend further
        for name in files:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in exts:
                continue
            full = os.path.join(dirpath, name)
            try:
                out.append((full, os.path.getsize(full)))
            except OSError:  # pragma: no cover - racing deletion
                continue
    return out


@dataclass(frozen=True, slots=True)
class CompletedDownloadSource:
    """A completed download awaiting import (FRG-PP-001/003/008)."""

    download_id: str
    output_path: str
    client_id: int | None = None
    client_title: str | None = None
    mappings: tuple[RemotePathMapping, ...] = ()

    async def gather(
        self, session: AsyncSession, ctx: ImportContext
    ) -> list[ImportCandidate]:
        """Produce candidates for this download (FRG-PP-003/008)."""
        mapped = apply_mappings(self.output_path, list(self.mappings))
        # Reconcile by download id once; the grab title feeds evidence and its
        # series/issue become the candidate's high-confidence hints.
        grab = (
            await session.execute(
                select(GrabHistoryRow).where(
                    GrabHistoryRow.download_id == self.download_id
                )
            )
        ).scalars().first()
        grab_title = grab.title if grab is not None else None
        grab_series_id = grab.series_id if grab is not None else None
        grab_issue_id = grab.issue_id if grab is not None else None

        if mapped.warning is not None:
            # Unmapped/foreign path: one blocked candidate naming the fix; the
            # file is never guessed at a local path (FRG-PP-008 scenario 2).
            return [
                ImportCandidate(
                    source_kind=SOURCE_DOWNLOAD,
                    local_path=mapped.path,
                    size=0,
                    file_name=Path(mapped.path).name,
                    folder_name=Path(mapped.path).parent.name or None,
                    container_root=mapped.path,
                    download_id=self.download_id,
                    client_title=self.client_title,
                    grab_title=grab_title,
                    grab_series_id=grab_series_id,
                    grab_issue_id=grab_issue_id,
                    mapping_warning=mapped.warning,
                )
            ]

        files = _iter_archive_files(
            mapped.path, ctx.archive_extensions, ctx.max_walk_depth
        )
        root = mapped.path if Path(mapped.path).is_dir() else str(Path(mapped.path).parent)
        return [
            ImportCandidate(
                source_kind=SOURCE_DOWNLOAD,
                local_path=path,
                size=size,
                file_name=Path(path).name,
                folder_name=Path(path).parent.name or None,
                container_root=root,
                download_id=self.download_id,
                client_title=self.client_title,
                grab_title=grab_title,
                grab_series_id=grab_series_id,
                grab_issue_id=grab_issue_id,
            )
            for path, size in files
        ]


@dataclass(frozen=True, slots=True)
class RescanSource:
    """A per-series disk rescan intake (FRG-SER-010, file-routing half)."""

    series_id: int
    #: Optional path override; defaults to the series' stored path.
    path_override: str | None = None

    async def gather(
        self, session: AsyncSession, ctx: ImportContext
    ) -> list[ImportCandidate]:
        """Produce candidates for untracked files under the series path.

        Files already linked to an issue-file record are skipped (FRG-SER-010);
        vanished-file cleanup and the rescan report are the flows command's job.
        """
        series = await session.get(SeriesRow, self.series_id)
        if series is None:
            return []
        path = self.path_override or series.path
        existing = set(
            (
                await session.execute(
                    select(IssueFileRow.path)
                    .join(IssueRow, IssueFileRow.issue_id == IssueRow.id)
                    .where(IssueRow.series_id == self.series_id)
                )
            )
            .scalars()
            .all()
        )
        files = _iter_archive_files(path, ctx.archive_extensions, ctx.max_walk_depth)
        return [
            ImportCandidate(
                source_kind=SOURCE_RESCAN,
                local_path=fpath,
                size=size,
                file_name=Path(fpath).name,
                folder_name=Path(fpath).parent.name or None,
                container_root=path,
                series_scope_id=self.series_id,
            )
            for fpath, size in files
            if fpath not in existing
        ]


__all__ = [
    "SOURCE_DOWNLOAD",
    "SOURCE_RESCAN",
    "CompletedDownloadSource",
    "ImportCandidate",
    "RescanSource",
]
