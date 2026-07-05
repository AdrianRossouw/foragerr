"""Release-title derivations shared by the specs, comparator, and de-dup.

All pure functions over already-parsed data — no I/O, no state.
"""

from __future__ import annotations

import re

from foragerr.parser.result import ParseResult

#: Container formats foragerr tracks. Kept lowercase; matched case-insensitively.
KNOWN_FORMATS: tuple[str, ...] = ("cbz", "cbr", "cb7", "pdf", "epub")

_FORMAT_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(KNOWN_FORMATS) + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def candidate_format(parsed: ParseResult, title: str) -> str | None:
    """Best-effort container format for a release, or ``None`` if unknown.

    Release titles rarely name their container, so this is deliberately
    permissive: prefer the parser's trailing-extension read, else the first
    explicit format token in the title. An unknown format is *not* an error —
    the format-allowed spec permits unknowns (they cannot be judged before the
    download exists) and import re-checks later.
    """
    if parsed.type:
        ext = parsed.type.lower()
        if ext in KNOWN_FORMATS:
            return ext
    match = _FORMAT_TOKEN_RE.search(title)
    if match:
        return match.group(1).lower()
    return None


def normalized_title(title: str) -> str:
    """A loose normalization of a whole release title for cross-indexer de-dup.

    Two indexers' copies of the same upload carry the same title; this folds
    case and non-alphanumeric runs so they collapse to one key. It is
    intentionally *not* the series matching-key (which strips articles and
    issue numbers) — here the full title's identity must be preserved.
    """
    folded = re.sub(r"[^0-9a-z]+", " ", title.casefold()).strip()
    return re.sub(r"\s+", " ", folded)
