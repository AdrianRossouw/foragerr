"""Index-stable tokenization (FRG-IMP-004).

Spaces, underscores, and commas always separate tokens; dots separate only
when they are the dominant separator (NZB-style names). ``(...)`` and
``[...]`` groups are atomic annotation tokens. Tokens carry their character
offset and stream index — position bookkeeping is by index, never by
first-occurrence value lookup, so repeated tokens (``Batman 66 66 (2016)``)
cannot corrupt boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .normalize import DASH_CHARS, fold

_HARD_SEPARATORS = frozenset({"_", ","})
_OPENERS = {"(": ")", "[": "]"}
_DASH_SET = frozenset("-" + DASH_CHARS)


class TokenKind(Enum):
    WORD = "word"
    GROUP_PAREN = "group-paren"
    GROUP_BRACKET = "group-bracket"
    DASH = "dash"
    HASH = "hash"


@dataclass(frozen=True, slots=True)
class Token:
    text: str  # original slice, including group delimiters
    inner: str  # group content without delimiters (== text for words)
    start: int  # character offset in the (extension-stripped) name
    index: int  # stable stream index
    kind: TokenKind
    folded: str  # fold(inner), computed once at construction (FRG-IMP-001)


def is_dot_dominant(name: str) -> bool:
    """True when dots are the dominant separator (NZB-style names)."""
    dots = name.count(".")
    if dots < 2:
        return False
    others = sum(1 for ch in name if ch.isspace() or ch in _HARD_SEPARATORS)
    return dots > others


def extra_separators(name: str) -> frozenset[str]:
    """Dominant-separator detection beyond the always-on set.

    * dots split when dot-dominant (NZB names);
    * ``+`` splits when the name has no base separators and 2+ pluses
      (URL-encoding artifacts: ``Swamp+Thing+003+(2012)``);
    * ``-`` splits when the name has no base separators, is not
      dot-dominant, and has 2+ hyphens (fully hyphen-mangled names:
      ``Justice-League-Beyond-005--2012---digital-Empire-``). Names with
      normal separators keep their hyphens (X-23, Spider-Man).
    """
    extras = set()
    if is_dot_dominant(name):
        extras.add(".")
    base = sum(1 for ch in name if ch.isspace() or ch in _HARD_SEPARATORS)
    if base == 0:
        if name.count("+") >= 2:
            extras.add("+")
        if "." not in extras and name.count("-") >= 2:
            extras.add("-")
    return frozenset(extras)


def _is_separator(ch: str, extras: frozenset[str]) -> bool:
    return ch.isspace() or ch in _HARD_SEPARATORS or ch in extras


def tokenize(name: str) -> list[Token]:
    """Tokenize ``name`` into an index-stable token stream. Never raises."""
    extras = extra_separators(name)
    raw: list[tuple[str, str, int, TokenKind]] = []  # text, inner, start, kind
    i = 0
    n = len(name)
    while i < n:
        ch = name[i]
        if _is_separator(ch, extras):
            i += 1
            continue
        if ch in _OPENERS:
            closer = _OPENERS[ch]
            end = name.find(closer, i + 1)
            if end == -1:
                end = n  # unclosed group: consume to end, never crash
                text = name[i:]
                inner = name[i + 1 :]
            else:
                text = name[i : end + 1]
                inner = name[i + 1 : end]
            kind = TokenKind.GROUP_PAREN if ch == "(" else TokenKind.GROUP_BRACKET
            raw.append((text, inner.strip(), i, kind))
            i = end + 1
            continue
        if ch in (")", "]"):  # stray closer: treat as separator
            i += 1
            continue
        # word token: run until separator, group opener, or stray closer
        start = i
        while i < n:
            ch = name[i]
            if _is_separator(ch, extras) or ch in _OPENERS or ch in (")", "]"):
                break
            i += 1
        word = name[start:i]
        if not word:
            continue
        if all(c in _DASH_SET for c in word):
            raw.append((word, word, start, TokenKind.DASH))
        elif word == "#":
            raw.append((word, word, start, TokenKind.HASH))
        else:
            raw.append((word, word, start, TokenKind.WORD))
    return [
        Token(text=t, inner=inner, start=s, index=idx, kind=k, folded=fold(inner))
        for idx, (t, inner, s, k) in enumerate(raw)
    ]
