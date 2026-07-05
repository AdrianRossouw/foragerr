"""Unicode-native normalization — the single folding source (FRG-IMP-005).

`matching_key()` is the one normalization function shared by parsing, series
matching, and renaming (the dynamic-name analogue). No second folding
implementation may exist anywhere in the codebase.

No sentinel substitution of any kind happens here or anywhere else in the
parser: titles containing substrings like ``XCV`` or ``c11`` round-trip
unmangled.
"""

from __future__ import annotations

import re
import unicodedata

#: Unicode dash variants folded to ASCII '-' for *matching* purposes only.
#: (hyphen, non-breaking hyphen, figure dash, en dash, em dash, horizontal
#:  bar, two-em dash, three-em dash, minus sign)
DASH_CHARS = "‐‑‒–—―⸺⸻−"

#: Curly single/double quotes folded to straight quotes for matching.
_QUOTE_MAP = {
    0x2018: "'",
    0x2019: "'",
    0x201A: "'",
    0x201B: "'",
    0x201C: '"',
    0x201D: '"',
    0x201E: '"',
}

_FOLD_TABLE = {ord(c): "-" for c in DASH_CHARS} | _QUOTE_MAP

#: Articles removed from the matching key (case-insensitive whole words).
_ARTICLES = frozenset({"the", "a", "an", "and"})

#: Punctuation collapsed to separators in the matching key.
_PUNCT_RE = re.compile(r"[/\\\-:;'\",&?!+*.()\[\]{}#|_~]+")
_SPACE_RE = re.compile(r"\s+")


def nfc(text: str) -> str:
    """Canonical composition applied once at the parser entry point."""
    return unicodedata.normalize("NFC", text)


def fold(text: str) -> str:
    """Fold for vocabulary/token comparison: dash + quote variants, casefold.

    Preserves digits, letters and structure — this is a *comparison* view;
    the original glyphs are always kept for output fields.
    """
    return text.translate(_FOLD_TABLE).casefold()


def matching_key(title: str) -> str:
    """Produce the normalized matching key for a series title.

    NFKD-aware, punctuation folded to spaces, articles removed, case and
    separators collapsed. Shared by parser, matcher, and renamer — the only
    folding implementation (FRG-IMP-005).
    """
    if title.isascii():  # fast path: NFKD and combining-strip are no-ops
        text = title.casefold()
    else:
        text = fold(unicodedata.normalize("NFKD", title))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _PUNCT_RE.sub(" ", text)
    words = [w for w in _SPACE_RE.split(text) if w]
    kept = [w for w in words if w not in _ARTICLES]
    if not kept:  # articles-only titles keep their words rather than vanish
        kept = words
    return " ".join(kept)
