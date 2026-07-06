"""Scan a series' folder and match existing files to issues (FRG-SER-005).

Walks the series path, parses each comic-archive filename through the change-2
parser, and records an ``issue_files`` row for every file that matches an
issue by (a) series-title matching key and (b) issue number. Unmatched files
are only counted/logged — this change deliberately does NOT create any
"unmatched files" table (import routing / library-import staging is change 6,
FRG-SER-010), so nothing out of scope is invented here.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any, Awaitable, Callable

from sqlalchemy import select

from foragerr.commands.registry import register_handler
from foragerr.commands.service import HandlerContext
from foragerr.config import Settings
from foragerr.db import Database
from foragerr.library import matching, repo
from foragerr.library.models import IssueFileRow, IssueRow
from foragerr.parser import ParseMode, ParseResult, parse
from foragerr.parser.result import Issue
from foragerr.parser.vocab import ARCHIVE_EXTENSIONS

from foragerr.library.flows._common import ScanSeriesCommand

logger = logging.getLogger("foragerr.library.flows.scan")

#: ``HandlerContext.offload``-compatible callable (``daemon_offload`` in
#: production): runs a blocking function on a thread so it never stalls the
#: shared event loop.
OffloadFn = Callable[..., Awaitable[Any]]


async def scan_series(
    db: Database,
    settings: Settings,
    series_id: int,
    *,
    offload: OffloadFn | None = None,
) -> str:
    """Match on-disk files under a series' path to its issues.

    Returns a ``"matched=N unmatched=M"`` summary (recorded as the command's
    job-history result). A missing series folder is not an error — it simply
    yields zero files.

    ``offload`` (the command handler passes ``ctx.offload``) runs the
    directory walk + per-file ``stat`` on a thread instead of the event loop
    — worth it on a slow/network-mounted library path. Direct callers (tests,
    scripts) may omit it, in which case the walk runs inline exactly as
    before.
    """
    async with db.read_session() as session:
        series = await repo.get_series(session, series_id)
        if series is None:
            return f"series {series_id} no longer exists; scan skipped"
        issues = await repo.list_issues_for_series(session, series.id)
        result = await session.execute(
            select(IssueFileRow.path)
            .join(IssueRow, IssueFileRow.issue_id == IssueRow.id)
            .where(IssueRow.series_id == series.id)
        )
        existing_paths = set(result.scalars().all())
        series_key = series.matching_key
        series_path = series.path
        reference_year = series.start_year or dt.date.today().year

    # Precompute each issue's parsed number once (same shape the filename
    # parser produces), so matching is a cheap in-memory comparison.
    issue_index = matching.build_issue_index(issues)

    files = (
        await offload(_collect_archive_files, series_path)
        if offload is not None
        else _collect_archive_files(series_path)
    )

    matched: list[tuple[int, str, int]] = []
    unmatched = 0
    for file_path, size in files:
        if file_path in existing_paths:
            continue  # already recorded by an earlier scan/import
        parsed = parse(
            os.path.basename(file_path),
            reference_year=reference_year,
            mode=ParseMode.FILENAME,
        )
        issue_id = _match_issue(parsed, series_key, issue_index)
        if issue_id is None:
            unmatched += 1
            logger.debug("scan: no issue match for %s", file_path)
            continue
        matched.append((issue_id, file_path, size))

    if matched:
        async with db.write_session() as session:
            for issue_id, path, size in matched:
                await repo.add_issue_file(
                    session, issue_id=issue_id, path=path, size=size
                )

    summary = f"matched={len(matched)} unmatched={unmatched}"
    logger.info("scan series %d: %s", series_id, summary)
    return summary


# --- matching ---------------------------------------------------------------


def _match_issue(
    parsed: ParseResult,
    series_key: str,
    issue_index: list[tuple[int, Issue]],
) -> int | None:
    """Return the id of the issue this parsed filename belongs to, or ``None``.

    A file matches when its parsed series-title matching key aligns with the
    series' stored key AND its parsed issue equals a stored issue's parsed
    number (value + suffix + name + infinity) — the shared
    :mod:`foragerr.library.matching` rules the importer uses too."""
    if not parsed.success or parsed.issue is None or parsed.matching_key is None:
        return None
    if not matching.series_title_matches(parsed.matching_key, series_key):
        return None
    return matching.match_issue_id(parsed.issue, issue_index)


# --- filesystem -------------------------------------------------------------


def _collect_archive_files(series_path: str) -> list[tuple[str, int]]:
    """The recursive series-folder archive walk (shared
    :func:`foragerr.library.matching.iter_archive_files`), materialized as a
    plain function so it can be handed to ``offload``/``asyncio.to_thread``."""
    return matching.iter_archive_files(series_path, ARCHIVE_EXTENSIONS)


# --- command handler --------------------------------------------------------


@register_handler("scan-series")
async def _handle_scan(command: ScanSeriesCommand, ctx: HandlerContext) -> str:
    return await scan_series(
        ctx.db, ctx.settings, command.series_id, offload=ctx.offload
    )
