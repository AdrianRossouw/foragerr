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

    @property
    def folded(self) -> str:
        return fold(self.inner)


def is_dot_dominant(name: str) -> bool:
    """True when dots are the dominant separator (NZB-style names)."""
    dots = name.count(".")
    if dots < 2:
        return False
    others = sum(1 for ch in name if ch.isspace() or ch in _HARD_SEPARATORS)
    return dots > others


def _is_separator(ch: str, dot_dominant: bool) -> bool:
    if ch.isspace() or ch in _HARD_SEPARATORS:
        return True
    return dot_dominant and ch == "."


def tokenize(name: str) -> list[Token]:
    """Tokenize ``name`` into an index-stable token stream. Never raises."""
    dot_dominant = is_dot_dominant(name)
    raw: list[tuple[str, str, int, TokenKind]] = []  # text, inner, start, kind
    i = 0
    n = len(name)
    while i < n:
        ch = name[i]
        if _is_separator(ch, dot_dominant):
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
            if _is_separator(ch, dot_dominant) or ch in _OPENERS or ch in (")", "]"):
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
        Token(text=t, inner=inner, start=s, index=idx, kind=k)
        for idx, (t, inner, s, k) in enumerate(raw)
    ]
