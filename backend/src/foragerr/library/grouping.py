"""Franchise-key derivation for volume grouping (FRG-SER-016).

A ComicVine *volume* is one *run* of a title — "Batman (2011)",
"Batman (2016)", "Batman (2025)" are three CV volumes of one franchise, and
ComicVine has no franchise entity to group them. :func:`franchise_key` derives
the grouping key we fold successive runs under: strip a *trailing* volume-year
``(YYYY)`` and a *trailing* ``Vol N`` / ``Volume N`` designator from the title,
then apply the one shared normalization (:func:`foragerr.parser.normalize.
matching_key`, FRG-IMP-005). So "Batman (2011)" and "Batman (2016)" both fold
to ``"batman"`` and share a group.

Pure and side-effect-free — the DB find-or-create + auto-group wiring lives in
:mod:`foragerr.library.repo`; this module only computes strings. Only a
*trailing* designator is stripped (a year mid-title is left alone) so distinct
titles are never over-merged.
"""

from __future__ import annotations

import re

from foragerr.parser.normalize import matching_key

#: A trailing 4-digit volume-year in parentheses, e.g. " (2011)".
_TRAILING_YEAR_RE = re.compile(r"\s*\((?:19|20)\d{2}\)\s*$")

#: A trailing ``Vol N`` / ``Volume N`` designator (case-insensitive), e.g.
#: " Vol 2", " Volume 3", " Vol. 2". ``\b`` before ``vol`` keeps it from
#: biting inside a word like "Frivol".
_TRAILING_VOL_RE = re.compile(r"\s*\bvol(?:ume)?\.?\s*\d+\s*$", re.IGNORECASE)


def _strip_designators(title: str) -> str:
    """Strip trailing ``(YYYY)`` and ``Vol N`` designators, in any order.

    Iterated so a stacked "Batman Vol 2 (2016)" (year then volume) fully
    reduces to "Batman" regardless of which trailing designator comes last.
    """
    text = title.strip()
    changed = True
    while changed:
        changed = False
        for pattern in (_TRAILING_YEAR_RE, _TRAILING_VOL_RE):
            stripped = pattern.sub("", text)
            if stripped != text:
                text = stripped.rstrip()
                changed = True
    return text.strip()


def franchise_display_title(title: str) -> str:
    """The stripped, still-cased display title for a *new* group's default name.

    Preserves the original glyphs/casing (unlike :func:`franchise_key`, which
    folds) — the franchise header shows "Batman", not "batman".
    """
    return _strip_designators(title)


def franchise_key(title: str) -> str | None:
    """The normalized franchise key a series folds to, or ``None``.

    ``None`` when the stripped title normalizes to empty (an untitled /
    designator-only edge) — such a series stays ungrouped rather than being
    forced into an unrelated group.
    """
    key = matching_key(_strip_designators(title))
    return key or None
