"""Series collected-edition (trade) book-type derivation (FRG-SER-018).

Types a *series/volume* by its collected-edition **book-type** from the series
title, reusing the SAME longest-first book-type cue vocabulary the filename
parser uses (:data:`foragerr.parser.vocab.BOOKTYPE_CUES` /
:func:`~foragerr.parser.vocab.booktype_cue_phrases`) — never a re-hardcoded cue
list. Pure and deterministic.

This is DISPLAY/NAMING metadata ONLY. It is deliberately independent of the
issue-level :class:`foragerr.library.models.IssueRow.issue_type` vocabulary
(which types an *issue* and DOES feed the pull matcher's guard), and no
book-type predicate derived here ever reaches ``repo.wanted_issues()`` /
``series_statistics`` — trades and singles are independent acquisition tracks
(the FRG-SER-019 invariant).

The returned value is a lowercased/underscored parser ``Booktype`` value
(``tpb``/``gn``/``hc``/``one_shot``); ``None`` = an ordinary single-issues run
(no collected-edition cue in the title). Only ``tpb``/``gn``/``hc`` are
*derivable* from a title cue — ``BOOKTYPE_CUES`` maps nothing to ``one_shot``,
so ``one_shot`` is reachable only via an explicit operator override.
"""

from __future__ import annotations

import re

from foragerr.parser.normalize import fold
from foragerr.parser.result import Booktype
from foragerr.parser.vocab import DEFAULT_OPTIONS, booktype_cue_phrases

#: Word tokens for phrase matching — folded alphanumeric runs, so a cue only
#: matches on a whole-word boundary (``"hc"`` never fires inside ``"Archie"``,
#: ``"gn"`` never inside ``"Gunslinger"``).
_WORD_RE = re.compile(r"[0-9a-z]+")


def _canonical(booktype: Booktype) -> str:
    """The stored string for a parser ``Booktype`` — lowercased, dashes to
    underscores (``Booktype.ONE_SHOT`` -> ``"one_shot"``, ``Booktype.TPB`` ->
    ``"tpb"``). Derived from the enum so the stored vocabulary never forks."""
    return booktype.value.lower().replace("-", "_")


#: The book-type string values a series may carry: the three collected editions
#: derivable from a title cue plus the operator-only ``one_shot``. Derived from
#: the parser :class:`~foragerr.parser.result.Booktype` enum so it never forks
#: from the parser vocabulary. Used by the edit-flow override validation.
COLLECTED_BOOKTYPES: tuple[str, ...] = tuple(
    _canonical(bt)
    for bt in (Booktype.TPB, Booktype.GN, Booktype.HC, Booktype.ONE_SHOT)
)


def _contains_phrase(tokens: list[str], phrase: tuple[str, ...]) -> bool:
    """Whether ``phrase`` occurs as a contiguous run within ``tokens``."""
    n = len(phrase)
    if n == 0:
        return False
    for i in range(len(tokens) - n + 1):
        if tuple(tokens[i : i + n]) == phrase:
            return True
    return False


def detect_series_booktype(title: str) -> str | None:
    """Derive a series' collected-edition book-type from its title (FRG-SER-018).

    Matches the title against the parser's book-type cues (longest phrase
    first, on whole-word boundaries) and returns the matched book-type as a
    lowercased/underscored ``Booktype`` value (``tpb``/``gn``/``hc``), or
    ``None`` when the title carries no collected-edition cue. Uses the SAME
    folding (:func:`foragerr.parser.normalize.fold`) and cue vocabulary
    (:func:`~foragerr.parser.vocab.booktype_cue_phrases`) as the filename
    parser — never a second cue list — so a title's typing can never disagree
    with what the parser reads from the same words.
    """
    tokens = _WORD_RE.findall(fold(title))
    if not tokens:
        return None
    # ``booktype_cue_phrases`` is longest-first, so the first contiguous match
    # wins (longest-match precedence, matching the filename parser).
    for phrase, booktype in booktype_cue_phrases(DEFAULT_OPTIONS):
        if _contains_phrase(tokens, phrase):
            return _canonical(booktype)
    return None
