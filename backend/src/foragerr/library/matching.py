"""Shared file↔issue matching helpers (FRG-SER-005, FRG-SER-010, FRG-PP-003).

The library scanner (:mod:`foragerr.library.flows.scan`) and the import pipeline
(:mod:`foragerr.importer.pipeline`) resolve on-disk comic files to library issues
by the identical rules: a loose series-title key match plus an exact parsed
issue-number match, over a once-built index of the series' parsed issue numbers,
and a bounded/​unbounded archive-file walk. Those rules lived as near-verbatim
copies in both places; this module is the single owner so the two paths can never
drift (a case-sensitivity fork was exactly such a drift).

Pure and I/O-light: the matching helpers touch no database (they read a
pre-built index) and only :func:`iter_archive_files` touches the filesystem.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Protocol

from foragerr.library.ordering import parse_issue_number
from foragerr.parser.result import Issue


def series_title_matches(parsed_key: str | None, series_key: str | None) -> bool:
    """Loose series-title match: exact, or the parsed key's tokens are a subset
    of the series key's (tolerates the parser under-extracting a subtitle/extra
    word the full ComicVine title carries).

    Deliberately NOT symmetric: allowing the series key to be a subset of the
    parsed key (the other direction) would let a short registered series name
    swallow a misfiled file that actually belongs to a different, longer series
    sharing that name as a prefix — a common pattern in comics ("Batman" /
    "Batman Beyond", "X-Men" / "X-Men Legacy", "Avengers" / "Avengers
    Academy", ...). Both callers scope the file to a single series' own context
    before matching, so only the narrower direction is safe to tolerate.
    """
    if not parsed_key or not series_key:
        return False
    if parsed_key == series_key:
        return True
    return set(parsed_key.split()) <= set(series_key.split())


def _norm_name(name: str | None) -> str | None:
    """Casefold an issue name for comparison (the scanner's canonical form)."""
    return name.casefold() if name else None


def issue_equal(a: Issue, b: Issue) -> bool:
    """Two parsed issues denote the same issue identity.

    Names are compared casefolded so a file whose issue-name casing differs from
    the stored issue still matches — the scanner already normalises this way, and
    the importer must agree or it silently misses case-differing matches the
    scanner accepts.
    """
    return (
        a.value == b.value
        and a.suffix == b.suffix
        and a.is_infinity == b.is_infinity
        and _norm_name(a.name) == _norm_name(b.name)
    )


class _HasIssueNumber(Protocol):
    id: int
    issue_number: str


def build_issue_index(issues: Iterable[_HasIssueNumber]) -> list[tuple[int, Issue]]:
    """Parse each issue's stored number once into ``(issue_id, parsed)`` pairs.

    Built once per scan/reconcile run and reused across every candidate file, so
    matching is a cheap in-memory comparison rather than an N×M re-parse."""
    return [(issue.id, parse_issue_number(issue.issue_number)) for issue in issues]


def match_issue_id(issue: Issue, issue_index: list[tuple[int, Issue]]) -> int | None:
    """Return the id of the indexed issue equal to ``issue``, or ``None``."""
    for issue_id, parsed in issue_index:
        if issue_equal(issue, parsed):
            return issue_id
    return None


def iter_archive_files(
    root: str,
    extensions: Iterable[str],
    *,
    max_depth: int | None = None,
) -> list[tuple[str, int]]:
    """Yield ``(absolute_path, size)`` for comic-archive files under ``root``.

    A single regular file passed as ``root`` yields just itself; a non-existent
    path yields nothing. ``max_depth`` bounds the walk (measured from ``root``,
    ``0`` = files directly in ``root``); ``None`` walks the whole tree (the
    library scanner's behaviour). A file that races deletion during the walk is
    skipped rather than raising.
    """
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
        if max_depth is not None:
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


__all__ = [
    "build_issue_index",
    "issue_equal",
    "iter_archive_files",
    "match_issue_id",
    "series_title_matches",
]
