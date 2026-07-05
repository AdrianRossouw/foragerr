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
from pathlib import Path
from typing import Iterator

from sqlalchemy import select

from foragerr.commands.registry import register_handler
from foragerr.commands.service import HandlerContext
from foragerr.config import Settings
from foragerr.db import Database
from foragerr.library import repo
from foragerr.library.models import IssueFileRow, IssueRow
from foragerr.library.ordering import parse_issue_number
from foragerr.parser import ParseMode, ParseResult, parse
from foragerr.parser.result import Issue
from foragerr.parser.vocab import ARCHIVE_EXTENSIONS

from foragerr.library.flows._common import ScanSeriesCommand

logger = logging.getLogger("foragerr.library.flows.scan")


async def scan_series(db: Database, settings: Settings, series_id: int) -> str:
    """Match on-disk files under a series' path to its issues.

    Returns a ``"matched=N unmatched=M"`` summary (recorded as the command's
    job-history result). A missing series folder is not an error — it simply
    yields zero files.
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
    issue_index = [
        (issue.id, parse_issue_number(issue.issue_number)) for issue in issues
    ]

    matched: list[tuple[int, str, int]] = []
    unmatched = 0
    for file_path, size in _iter_archive_files(series_path):
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
    number (value + suffix + name + infinity)."""
    if not parsed.success or parsed.issue is None or parsed.matching_key is None:
        return None
    if not _series_title_matches(parsed.matching_key, series_key):
        return None
    for issue_id, issue_number in issue_index:
        if _issue_equal(parsed.issue, issue_number):
            return issue_id
    return None


def _series_title_matches(parsed_key: str, series_key: str) -> bool:
    """Loose series-title match: exact, or one key's tokens are a subset of
    the other's (tolerates a subtitle/extra word on either side)."""
    if not parsed_key or not series_key:
        return False
    if parsed_key == series_key:
        return True
    parsed_tokens = set(parsed_key.split())
    series_tokens = set(series_key.split())
    return series_tokens <= parsed_tokens or parsed_tokens <= series_tokens


def _issue_equal(a: Issue, b: Issue) -> bool:
    return (
        a.value == b.value
        and a.suffix == b.suffix
        and a.is_infinity == b.is_infinity
        and _norm_name(a.name) == _norm_name(b.name)
    )


def _norm_name(name: str | None) -> str | None:
    return name.casefold() if name else None


# --- filesystem -------------------------------------------------------------


def _iter_archive_files(series_path: str) -> Iterator[tuple[str, int]]:
    """Yield ``(absolute_path, size)`` for every comic-archive file under the
    series folder (recursively). A non-existent folder yields nothing."""
    base = Path(series_path)
    if not base.exists():
        return
    for dirpath, _dirs, files in os.walk(base):
        for name in files:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in ARCHIVE_EXTENSIONS:
                continue
            full = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(full)
            except OSError:  # pragma: no cover - racing deletion
                continue
            yield full, size


# --- command handler --------------------------------------------------------


@register_handler("scan-series")
async def _handle_scan(command: ScanSeriesCommand, ctx: HandlerContext) -> str:
    return await scan_series(ctx.db, ctx.settings, command.series_id)
