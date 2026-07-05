"""Persisted issue ordering keys, reusing the change-2 ordering implementation.

FRG-SER-002's "issues sort in reading order via the persisted ordering key"
scenario needs a *stored, string-sortable* form of the parser's total-order
:func:`foragerr.parser.ordering.sort_key` tuple, computed straight from a
ComicVine issue-number string (``"1"``, ``"1.5"``, ``"1.MU"``, ``"½"`` —
FRG-SER-002) rather than from a parsed filename.

The filename parser's own entrypoint (:mod:`foragerr.parser`) is tokenizer-
driven and expects a whole filename/folder string, not a bare issue-number
field — there is no existing "parse one issue number" function to call
verbatim. This module is a small, deliberately narrow adapter: it builds the
shared :class:`foragerr.parser.result.Issue` value straight from a CV
issue-number string using the same primitives the filename grammar uses
(:func:`foragerr.parser.grammar.to_fraction`, the fraction glyph table, and
the shared issue-suffix vocabulary from :mod:`foragerr.parser.vocab`), then
hands that ``Issue`` to the *one* ordering implementation
(:func:`foragerr.parser.ordering.sort_key`) — so ranking/tie-break rules
(class rank, suffix vocab order, name text) are never reimplemented here.

The resulting ``SortKey`` tuple (``(infinity_rank, Fraction, class_rank,
suffix_rank, suffix_text, name_text)``) is encoded to a fixed-width,
lexicographically-sortable TEXT string so ``ORDER BY ordering_key`` in SQL
agrees with the tuple order without loading rows into Python first. This is
an M1 implementation choice (design decision 1 says only "persisted from the
change-2 ordering implementation" without prescribing the storage form) —
documented here for anyone extending it.
"""

from __future__ import annotations

import re
from decimal import Decimal, getcontext
from fractions import Fraction

from foragerr.parser.grammar import FRACTION_GLYPHS, to_fraction
from foragerr.parser.ordering import SortKey, sort_key
from foragerr.parser.result import Issue
from foragerr.parser.vocab import (
    DEFAULT_OPTIONS,
    ParseOptions,
    issue_suffix_set,
    single_letter_suffix_set,
)

getcontext().prec = 50  # exact-enough decimal division for sort-key encoding

_FRACTION_GLYPH_RE = re.compile(r"^(\d*(?:\.\d+)?)([½¼¾])$")
_SUFFIX_RE = re.compile(r"^(\d+(?:\.\d+)?)[.\-]?([A-Za-z]+)!?$")

#: Bound matching the parser's own numeric-token cap (FRG-IMP grammar guard);
#: keeps the sort-key encoding's fixed integer width safely in range.
_MAX_INTEGER_DIGITS = 13


def parse_issue_number(raw: str | None, options: ParseOptions = DEFAULT_OPTIONS) -> Issue:
    """Build the shared :class:`Issue` value from a bare CV issue-number string.

    Deliberately narrower than the full filename grammar: no annotations,
    no ranges, no token stream — just the numeric/suffix/named-issue shapes
    ComicVine actually sends in its ``issue_number`` field. Falls back to a
    named issue (preserving the raw text) for anything else, so unusual CV
    issue numbers still get a total, deterministic ordering position instead
    of raising.
    """
    if raw is None:
        return Issue(value=None, display="")
    if not isinstance(raw, str):
        raise TypeError(
            "issue numbers are stored as TEXT; pass a string "
            f"(got {type(raw).__name__}: {raw!r})"
        )
    text = raw.strip()
    if not text:
        return Issue(value=None, display="")
    if text == "∞":
        return Issue(value=None, display=text, is_infinity=True)

    m = _FRACTION_GLYPH_RE.match(text)
    if m:
        base, glyph = m.groups()
        value = FRACTION_GLYPHS[glyph]
        if base:
            base_val = to_fraction(base)
            if base_val is not None:
                value = base_val + value
        return Issue(value=value, display=text)

    value = to_fraction(text)
    if value is not None:
        return Issue(value=value, display=text)

    m = _SUFFIX_RE.match(text)
    if m:
        num_text, alpha = m.groups()
        num_value = to_fraction(num_text)
        canonical = alpha.upper()
        vocab = issue_suffix_set(options) | single_letter_suffix_set(options)
        if num_value is not None and canonical in vocab:
            return Issue(value=num_value, display=text, suffix=canonical)

    # Named/unrecognized issue number (e.g. a CV oddity): preserve verbatim,
    # ordered by name text like the filename parser's named-issue path.
    return Issue(value=None, display=text, name=text.casefold())


def _fraction_to_sortable(value: Fraction) -> str:
    """Fixed-width decimal encoding of a (possibly negative) Fraction.

    Shifts by a large constant so negative issue numbers (rare but real —
    some FCBD issues are numbered ``0``/``-1``) sort before positive ones as
    plain text, then zero-pads to a fixed integer width and a fixed 6-digit
    fractional width so string comparison matches numeric comparison.
    """
    offset = Decimal(10**_MAX_INTEGER_DIGITS)
    shifted = Decimal(value.numerator) / Decimal(value.denominator) + offset
    quantized = shifted.quantize(Decimal("1.000000"))
    integer_part, _, frac_part = str(quantized).partition(".")
    return f"{integer_part.zfill(_MAX_INTEGER_DIGITS + 1)}.{frac_part.ljust(6, '0')}"


def encode_sort_key(key: SortKey) -> str:
    """Encode a :data:`~foragerr.parser.ordering.SortKey` tuple as sortable TEXT."""
    infinity_rank, value, class_rank, suffix_rank, suffix_text, name_text = key
    return "|".join(
        (
            f"{infinity_rank:01d}",
            _fraction_to_sortable(value),
            f"{class_rank:01d}",
            f"{suffix_rank:05d}",
            suffix_text,
            name_text,
        )
    )


def ordering_key_for(raw_issue_number: str | None, options: ParseOptions = DEFAULT_OPTIONS) -> str:
    """The persisted ``ordering_key`` value for a CV issue-number string."""
    issue = parse_issue_number(raw_issue_number, options)
    return encode_sort_key(sort_key(issue, options))
