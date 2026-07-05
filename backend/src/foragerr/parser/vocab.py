"""Data-driven vocabularies for the parser (FRG-IMP-006/-009/-016/-017).

Every behavioral vocabulary is *data* on :class:`ParseOptions`, never code
branches, so callers can extend them without code changes (FRG-IMP-009's
configurable-suffix scenario). A small known-group list may exist only for
scoring/disambiguation — never for correctness — and none exists today.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from functools import lru_cache

from .normalize import fold
from .result import Booktype, IssueClassification

#: Comic archive extensions — the single definition (FRG-IMP-006), shared by
#: the parser and (later) the library walker. Lowercase, no dots. ``.cbt`` is
#: a deliberate addition over Mylar; ``.epub`` is deliberately out of scope.
ARCHIVE_EXTENSIONS: tuple[str, ...] = ("cbz", "cbr", "cb7", "cbt", "pdf")

#: Multi-letter alphanumeric issue-suffix vocabulary (FRG-IMP-009), canonical
#: uppercase. Matched case-insensitively in glued (``027AU``), space (``10
#: AI``) and dotted (``008.NOW``) forms. Note the deliberate omissions vs
#: Mylar: BLACK/WHITE/DARK/LIGHT invite mid-title false positives (corpus row
#: 29), and "Director's Cut" is classified as an edition designator instead
#: of an issue suffix (corpus row 30 corrected expectation).
ISSUE_SUFFIXES: tuple[str, ...] = (
    "AU",
    "AI",
    "INH",
    "NOW",
    "BEY",
    "MU",
    "HU",
    "LR",
    "DEATHS",
    "ALPHA",
    "OMEGA",
    "SUMMER",
    "SPRING",
    "FALL",
    "WINTER",
    "PREVIEW",
)

#: Single-letter suffixes fire only glued to digits (``15A``, ``600-X``) —
#: never as free-standing tokens (guards ``Cover B`` etc., FRG-IMP-009).
SINGLE_LETTER_SUFFIXES: tuple[str, ...] = ("A", "B", "C", "X", "O")

#: Edition/quality annotations (FRG-IMP-017), folded-lowercase. Multi-word
#: entries match across tokens. ``digital tpb`` doubles as a TPB booktype cue.
EDITION_TAGS: tuple[str, ...] = (
    "digital",
    "webrip",
    "web-rip",
    "c2c",
    "ctc",
    "deluxe edition",
    "director's cut",
    "digital tpb",
    "complete",
    "remastered",
)

#: Booktype cues (FRG-IMP-016), folded-lowercase -> enum. Multi-word forms
#: are matched across adjacent tokens (fixing Mylar's unreachable
#: ``graphic novel`` branch).
BOOKTYPE_CUES: dict[str, Booktype] = {
    "tpb": Booktype.TPB,
    "trade paperback": Booktype.TPB,
    "digital tpb": Booktype.TPB,
    "gn": Booktype.GN,
    "graphic novel": Booktype.GN,
    "hc": Booktype.HC,
    "hardcover": Booktype.HC,
}

#: Annual/special classification markers (FRG-IMP-015), folded-lowercase.
ANNUAL_MARKERS: dict[str, IssueClassification] = {
    "annual": IssueClassification.ANNUAL,
    "biannual": IssueClassification.BIANNUAL,
    "bi-annual": IssueClassification.BIANNUAL,
    "special": IssueClassification.SPECIAL,
}

#: Season words consumed together with an adjacent marker
#: (``Summer Special`` -> SPECIAL, corpus row 58 corrected expectation).
SEASON_WORDS: tuple[str, ...] = ("summer", "spring", "fall", "autumn", "winter")

#: Month names for cover-date forms like ``(June 2019)`` (FRG-IMP-013).
MONTH_NAMES: dict[str, int] = {
    name: i + 1
    for i, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        )
    )
} | {
    abbr: i + 1
    for i, abbr in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
    )
}


@dataclass(frozen=True, slots=True)
class ParseOptions:
    """Explicit, immutable options object — the only configuration channel.

    Behavior never depends on global config, watchlists, DB state, or the
    clock (FRG-IMP-002); everything variable lives here as data.
    """

    issue_suffixes: tuple[str, ...] = ISSUE_SUFFIXES
    single_letter_suffixes: tuple[str, ...] = SINGLE_LETTER_SUFFIXES
    edition_tags: tuple[str, ...] = EDITION_TAGS
    booktype_cues: tuple[tuple[str, Booktype], ...] = tuple(BOOKTYPE_CUES.items())
    annual_markers: tuple[tuple[str, IssueClassification], ...] = tuple(
        ANNUAL_MARKERS.items()
    )
    season_words: tuple[str, ...] = SEASON_WORDS
    extensions: tuple[str, ...] = ARCHIVE_EXTENSIONS
    include_trace: bool = False

    def with_suffixes(self, *extra: str) -> "ParseOptions":
        """Data-only vocabulary extension (FRG-IMP-009 scenario)."""
        return replace(
            self, issue_suffixes=self.issue_suffixes + tuple(s.upper() for s in extra)
        )


DEFAULT_OPTIONS = ParseOptions()


# ---------------------------------------------------------------------------
# Derived-vocabulary accessors (FRG-IMP-001 efficiency).
#
# ``ParseOptions`` is a frozen, fully-hashable dataclass, so these derivations
# are memoized per options object instead of being rebuilt on every call/token.
# This is the single normalization site for each derived form — in particular
# the uppercase issue-suffix set has ONE definition here (previously rebuilt in
# grammar, ordering, and the space-suffix attach path).


@lru_cache(maxsize=None)
def folded_edition_tags(options: ParseOptions) -> frozenset[str]:
    """Whole edition tags, folded, for whole-text edition matching."""
    return frozenset(fold(tag) for tag in options.edition_tags)


@lru_cache(maxsize=None)
def issue_suffix_set(options: ParseOptions) -> frozenset[str]:
    """Uppercase multi-letter issue-suffix vocabulary (the one definition)."""
    return frozenset(s.upper() for s in options.issue_suffixes)


@lru_cache(maxsize=None)
def single_letter_suffix_set(options: ParseOptions) -> frozenset[str]:
    """Uppercase single-letter suffix vocabulary."""
    return frozenset(s.upper() for s in options.single_letter_suffixes)


@lru_cache(maxsize=None)
def suffix_vocab_order(options: ParseOptions) -> tuple[str, ...]:
    """Ordered uppercase suffix vocabulary for stable ``sort_key`` ranking."""
    return tuple(s.upper() for s in options.issue_suffixes) + tuple(
        s.upper() for s in options.single_letter_suffixes
    )


@lru_cache(maxsize=None)
def extension_re(options: ParseOptions) -> re.Pattern[str]:
    """Compiled trailing-extension pattern (single trailing occurrence)."""
    return re.compile(
        r"\.(" + "|".join(re.escape(e) for e in options.extensions) + r")$",
        re.IGNORECASE,
    )


@lru_cache(maxsize=None)
def booktype_cue_phrases(
    options: ParseOptions,
) -> tuple[tuple[tuple[str, ...], Booktype], ...]:
    """Folded booktype-cue phrases, longest first (longest-match precedence)."""
    return tuple(
        sorted(
            ((tuple(fold(c).split()), bt) for c, bt in options.booktype_cues),
            key=lambda p: -len(p[0]),
        )
    )


@lru_cache(maxsize=None)
def edition_phrases(
    options: ParseOptions,
) -> tuple[tuple[tuple[str, ...], Booktype | None], ...]:
    """Multi-word edition phrases, folded, each paired with the booktype it
    doubles as (``digital tpb`` -> TPB) or ``None``; longest first."""
    pairs: list[tuple[tuple[str, ...], Booktype | None]] = []
    for tag in options.edition_tags:
        if " " not in tag:
            continue
        phrase = tuple(fold(tag).split())
        joined = " ".join(phrase)
        bt = next((b for c, b in options.booktype_cues if joined == fold(c)), None)
        pairs.append((phrase, bt))
    return tuple(sorted(pairs, key=lambda p: -len(p[0])))
