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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.importer.context import ImportContext

# NOTE: the `foragerr.downloads` imports (GrabHistoryRow, apply_mappings) are
# deliberately DEFERRED into `CompletedDownloadSource.gather`. Importing any
# `foragerr.downloads` submodule initializes that package, whose init chain
# (downloads → clients → search_ops → library.flows → library_import →
# foragerr.importer) closes an import cycle that breaks
# `import foragerr.importer` whenever the importer package is the entry point
# (e.g. a scoped test run). The typing-only name stays under TYPE_CHECKING.
#
# GUARD: this is not a bare style preference — re-introducing a *top-level*
# `foragerr.downloads` import here (or in the importer `__init__`) silently
# re-opens the cycle. `tests/test_nfr_startup.py`'s isolated-importability
# regression imports every importer/flows leaf as the sole entry point in a
# fresh subprocess, so such a regression fails CI rather than only a scoped
# test run (FRG-NFR-001).
if TYPE_CHECKING:  # pragma: no cover — typing-only, never imported at runtime
    from foragerr.downloads.pathmap import RemotePathMapping

# Source-kind discriminators carried on the candidate (data, not a type switch).
# Canonically owned by :mod:`foragerr.importer.history` (the provenance column
# uses the same values); re-exported here so callers keep one import site.
from foragerr.importer.history import (
    SOURCE_DOWNLOAD,
    SOURCE_LIBRARY,
    SOURCE_MANUAL,
    SOURCE_RESCAN,
)
from foragerr.library import matching
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow


@dataclass(frozen=True, slots=True)
class ManualOverride:
    """A per-file manual mapping correction (FRG-PP-016, design decision 2).

    Minimal and human-supplied: it pins the series/issue a file resolves to (top
    priority in :func:`~foragerr.importer.pipeline.reconcile`) and, optionally, a
    ``format`` that feeds the upgrade check only. An override MAY bypass only the
    series/issue mapping specs — never the archive-valid / junk / free-space /
    already-imported / upgrade safety specs, which still run in full.
    """

    series_id: int | None = None
    issue_id: int | None = None
    format: str | None = None  # e.g. "cbz" — feeds ImportEvaluation.new_format


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
    #: A manual mapping override (FRG-PP-016); ``None`` for the two M1 sources, so
    #: they are wholly untouched. When present it is the top-priority
    #: reconciliation layer (validated against real rows before it is trusted).
    override: ManualOverride | None = None


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
        # Deferred to keep `foragerr.importer` importable standalone (see the
        # module-level note about the downloads package's import cycle).
        from foragerr.downloads.models import GrabHistoryRow
        from foragerr.downloads.pathmap import apply_mappings

        mapped = apply_mappings(self.output_path, list(self.mappings))
        # Reconcile by download id once; the grab title feeds evidence and its
        # series/issue become the candidate's high-confidence hints. A re-grab
        # of the same download id leaves several rows, so take the LATEST by id
        # (deterministic) rather than an arbitrary one (FRG-PP-004).
        grab = (
            await session.execute(
                select(GrabHistoryRow)
                .where(GrabHistoryRow.download_id == self.download_id)
                .order_by(GrabHistoryRow.id.desc())
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

        files = matching.iter_archive_files(
            mapped.path, ctx.archive_extensions, max_depth=ctx.max_walk_depth
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
        files = matching.iter_archive_files(
            path, ctx.archive_extensions, max_depth=ctx.max_walk_depth
        )
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


@dataclass(frozen=True, slots=True)
class ManualImportSource:
    """The manual-import intake (FRG-PP-016, design decision 1).

    Produces the SAME neutral :class:`ImportCandidate` list every other source
    produces — nothing downstream forks — stamped ``source_kind = SOURCE_MANUAL``
    and carrying per-file :class:`ManualOverride`s. Three shapes, matching the
    three ways the manual view is driven:

    - ``download`` given — an ``import_blocked`` download: delegates to
      :meth:`CompletedDownloadSource.gather` VERBATIM so remote-path mapping
      (FRG-PP-008), the latest grab-record lookup, and the grab hints are reused,
      not re-implemented, then re-stamps ``SOURCE_MANUAL`` and attaches overrides.
      A mapping-warning candidate is passed through unchanged.
    - ``folder_path`` given — an arbitrary folder: walks it with the identical
      bounded :func:`matching.iter_archive_files` intake ``RescanSource`` uses,
      emitting unscoped candidates (no grab hints).
    - ``files`` given — the execute path: an explicit list of picked file paths
      (each with its override), imported as their own candidates.

    ``overrides`` maps a candidate ``local_path`` to its :class:`ManualOverride`.
    """

    download: CompletedDownloadSource | None = None
    folder_path: str | None = None
    files: tuple[str, ...] = ()
    overrides: dict[str, ManualOverride] = field(default_factory=dict)

    async def gather(
        self, session: AsyncSession, ctx: ImportContext
    ) -> list[ImportCandidate]:
        """Produce manual candidates (FRG-PP-016)."""
        if self.download is not None:
            base = await self.download.gather(session, ctx)
            return [
                replace(
                    candidate,
                    source_kind=SOURCE_MANUAL,
                    override=self.overrides.get(candidate.local_path),
                )
                for candidate in base
            ]
        if self.folder_path is not None:
            found = matching.iter_archive_files(
                self.folder_path, ctx.archive_extensions, max_depth=ctx.max_walk_depth
            )
            return [self._candidate(path, size) for path, size in found]
        return [self._candidate_for(path) for path in self.files]

    def _candidate_for(self, path: str) -> ImportCandidate:
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        return self._candidate(path, size)

    def _candidate(self, path: str, size: int) -> ImportCandidate:
        return ImportCandidate(
            source_kind=SOURCE_MANUAL,
            local_path=path,
            size=size,
            file_name=Path(path).name,
            folder_name=Path(path).parent.name or None,
            container_root=str(Path(path).parent),
            override=self.overrides.get(path),
        )


@dataclass(frozen=True, slots=True)
class LibraryImportSource:
    """The existing-library mass-import intake (FRG-IMP-023).

    Produces the SAME neutral :class:`ImportCandidate` list every other source
    produces — nothing downstream forks — following :class:`ManualImportSource`'s
    shape: an explicit file list plus overrides, stamped
    ``source_kind = SOURCE_LIBRARY``. The library-import flow builds one source
    per CONFIRMED staging group after creating (or finding) the group's series,
    injecting the resolved ``series_id`` here — the importer never imports flow
    code (design decision 8).

    Each candidate pins the group's confirmed series two ways: a series-only
    :class:`ManualOverride` (human intent — the confirmed/corrected volume wins
    even when the filename parse disagrees with the ComicVine title) and
    ``series_scope_id`` (so the embedded-ComicInfo layer and the filename
    heuristic stay confined to this series). The ISSUE mapping deliberately
    stays heuristic/embedded — the user confirmed a series match, not a
    per-file issue mapping — and safety specs run in full as always.
    """

    series_id: int
    files: tuple[str, ...] = ()
    #: The group's folder (cleanup boundary + candidate container root).
    container_root: str | None = None

    async def gather(
        self, session: AsyncSession, ctx: ImportContext
    ) -> list[ImportCandidate]:
        """Produce candidates for the group's still-present, still-unregistered
        files.

        A file that vanished between scan and execute is skipped (never an
        error — the staging re-check re-runs the scan); a deleted series
        (raced between add and import) yields nothing. Files already linked to
        an issue-file record are skipped exactly like :class:`RescanSource`
        does (FRG-IMP-023): re-running a partially-imported group must
        re-candidate only its unregistered files, never block an
        already-imported file against itself.
        """
        series = await session.get(SeriesRow, self.series_id)
        if series is None:
            return []
        tracked = set(
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
        out: list[ImportCandidate] = []
        for path in self.files:
            if path in tracked:
                continue  # already registered by an earlier (partial) run
            try:
                size = os.path.getsize(path)
            except OSError:
                continue  # vanished since the scan staged it
            out.append(
                ImportCandidate(
                    source_kind=SOURCE_LIBRARY,
                    local_path=path,
                    size=size,
                    file_name=Path(path).name,
                    folder_name=Path(path).parent.name or None,
                    container_root=self.container_root or str(Path(path).parent),
                    series_scope_id=self.series_id,
                    override=ManualOverride(series_id=self.series_id),
                )
            )
        return out


__all__ = [
    "SOURCE_DOWNLOAD",
    "SOURCE_LIBRARY",
    "SOURCE_MANUAL",
    "SOURCE_RESCAN",
    "CompletedDownloadSource",
    "ImportCandidate",
    "LibraryImportSource",
    "ManualImportSource",
    "ManualOverride",
    "RescanSource",
]
