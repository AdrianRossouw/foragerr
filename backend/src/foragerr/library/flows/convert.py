"""On-demand CBR→CBZ conversion, per issue and per series (FRG-PP-018).

The operator-triggered counterpart to the convert-at-import step. A ``convert-
series`` / ``convert-issue`` command routes every CBR library file of the target
through :func:`foragerr.importer.convert.apply_conversion` under the SAME
verify-before-discard semantics as the import path; already-CBZ (and any other
non-CBR) files are skipped as no-ops (FRG-PP-018). Unlike the import-time policy,
on-demand conversion is explicit and does NOT read the ``convert_cbr_to_cbz``
flag.

Both commands run on the ``pp`` pool and share the importer's file-mutation
exclusivity group, so a conversion can never mutate the library concurrently with
an import or a rescan (FRG-SER-010). Each file is converted in its OWN
``write_session`` so a mid-batch failure isolates to that one file — the same
per-file isolation :func:`foragerr.importer.rename_ops.execute_renames` uses.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, ClassVar, Literal

from sqlalchemy import select

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.config import Settings
from foragerr.db import Database, utcnow
from foragerr.importer import (
    IMPORT_FILE_MUTATION_GROUP,
    ImportContext,
    convert,
    history,
    media_management_fields,
)
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow

logger = logging.getLogger("foragerr.library.flows.convert")

OffloadFn = Callable[..., Awaitable[Any]]


@register_command
class ConvertSeriesCommand(BaseCommand):
    """Convert every CBR file of one series to CBZ (FRG-PP-018).

    Runs on the ``pp`` pool under the importer file-mutation exclusivity group so
    it never mutates the library concurrently with an import/rescan."""

    name: Literal["convert-series"] = "convert-series"
    workload_class: ClassVar[str] = "pp"
    exclusivity_group: ClassVar[str | None] = IMPORT_FILE_MUTATION_GROUP
    series_id: int


@register_command
class ConvertIssueCommand(BaseCommand):
    """Convert every CBR file of one issue to CBZ (FRG-PP-018)."""

    name: Literal["convert-issue"] = "convert-issue"
    workload_class: ClassVar[str] = "pp"
    exclusivity_group: ClassVar[str | None] = IMPORT_FILE_MUTATION_GROUP
    issue_id: int


@dataclass(frozen=True, slots=True)
class ConvertReport:
    """The outcome of an on-demand conversion run (FRG-PP-018)."""

    #: New ``.cbz`` paths for files that converted.
    converted: tuple[str, ...]
    #: Non-CBR files skipped as no-ops (already CBZ, etc.).
    skipped: int
    #: Files whose conversion failed verification (original kept).
    failed: int

    def summary(self) -> str:
        return (
            f"converted={len(self.converted)} skipped={self.skipped} "
            f"failed={self.failed}"
        )


@dataclass(frozen=True, slots=True)
class _FileRow:
    issue_file_id: int
    path: str
    issue_id: int
    series_id: int | None


async def _load_series_files(db: Database, series_id: int) -> list[_FileRow]:
    async with db.read_session() as session:
        rows = (
            await session.execute(
                select(IssueFileRow.id, IssueFileRow.path, IssueRow.id, IssueRow.series_id)
                .join(IssueRow, IssueFileRow.issue_id == IssueRow.id)
                .where(IssueRow.series_id == series_id)
                .order_by(IssueFileRow.id)
            )
        ).all()
    return [_FileRow(fid, path, iid, sid) for fid, path, iid, sid in rows]


async def _load_issue_files(db: Database, issue_id: int) -> list[_FileRow]:
    async with db.read_session() as session:
        rows = (
            await session.execute(
                select(IssueFileRow.id, IssueFileRow.path, IssueRow.id, IssueRow.series_id)
                .join(IssueRow, IssueFileRow.issue_id == IssueRow.id)
                .where(IssueRow.id == issue_id)
                .order_by(IssueFileRow.id)
            )
        ).all()
    return [_FileRow(fid, path, iid, sid) for fid, path, iid, sid in rows]


async def _convert_files(
    db: Database,
    settings: Settings | None,
    files: list[_FileRow],
    *,
    offload: OffloadFn | None,
    now: dt.datetime,
) -> ConvertReport:
    """Convert each file in its own write_session (per-file isolation)."""
    ctx = ImportContext(
        library_root=".",
        config_dir=str(settings.config_dir) if settings is not None else ".",
        reference_year=now.year,
        now=now,
        offload=offload,
        **media_management_fields(settings),
    )
    converted: list[str] = []
    skipped = 0
    failed = 0
    for row in files:
        async with db.write_session() as session:
            new_path = await convert.apply_conversion(
                session,
                issue_file_id=row.issue_file_id,
                source_path=row.path,
                series_id=row.series_id,
                issue_id=row.issue_id,
                now=now,
                source=history.SOURCE_MANUAL,
                offload=offload,
            )
        if new_path is not None:
            converted.append(new_path)
        elif await _was_cbr(row.path, offload):
            failed += 1  # a CBR that returned None recorded convert_failed
        else:
            skipped += 1  # non-CBR no-op
    report = ConvertReport(
        converted=tuple(converted), skipped=skipped, failed=failed
    )
    return report


async def _was_cbr(path: str, offload: OffloadFn | None) -> bool:
    """Whether ``path`` was a CBR at classification time — distinguishes a
    verification failure (CBR, original kept) from a skip (non-CBR no-op). Read
    after the swap: a converted file is now a .cbz, so this is only consulted for
    the ``new_path is None`` case where the original .cbr remains on disk."""
    if offload is not None:
        return await offload(convert.is_cbr_file, path)
    return convert.is_cbr_file(path)


async def convert_series(
    db: Database,
    settings: Settings | None,
    series_id: int,
    *,
    offload: OffloadFn | None = None,
    now: dt.datetime | None = None,
) -> ConvertReport:
    """Convert every CBR file of one series to CBZ (FRG-PP-018).

    A missing series yields an empty report rather than an error. Each CBR
    converts under verify-before-discard; non-CBR files are skipped as no-ops."""
    now = now or utcnow()
    async with db.read_session() as session:
        if await session.get(SeriesRow, series_id) is None:
            logger.info("convert series %d: series gone; skipped", series_id)
            return ConvertReport((), 0, 0)
    files = await _load_series_files(db, series_id)
    report = await _convert_files(db, settings, files, offload=offload, now=now)
    logger.info("convert series %d: %s", series_id, report.summary())
    return report


async def convert_issue(
    db: Database,
    settings: Settings | None,
    issue_id: int,
    *,
    offload: OffloadFn | None = None,
    now: dt.datetime | None = None,
) -> ConvertReport:
    """Convert every CBR file of one issue to CBZ (FRG-PP-018)."""
    now = now or utcnow()
    files = await _load_issue_files(db, issue_id)
    report = await _convert_files(db, settings, files, offload=offload, now=now)
    logger.info("convert issue %d: %s", issue_id, report.summary())
    return report


@register_handler("convert-series")
async def _handle_convert_series(command: ConvertSeriesCommand, ctx: HandlerContext) -> str:
    report = await convert_series(
        ctx.db, ctx.settings, command.series_id, offload=ctx.offload
    )
    return report.summary()


@register_handler("convert-issue")
async def _handle_convert_issue(command: ConvertIssueCommand, ctx: HandlerContext) -> str:
    report = await convert_issue(
        ctx.db, ctx.settings, command.issue_id, offload=ctx.offload
    )
    return report.summary()


__all__ = [
    "ConvertIssueCommand",
    "ConvertReport",
    "ConvertSeriesCommand",
    "convert_issue",
    "convert_series",
]
