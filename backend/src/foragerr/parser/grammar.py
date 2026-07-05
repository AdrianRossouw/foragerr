"""Issue/volume/year/count grammar over the token stream (FRG-IMP-007..013).

All regexes are bounded (no nested quantifiers over user-controlled spans) —
reviewed against catastrophic backtracking, and exercised by the fuzz sweep
with a per-parse wall-clock ceiling. All numeric conversions are guarded:
digit runs longer than the caps below are treated as title content, so
``int()``/``Fraction()`` can never raise on adversarial input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from .normalize import fold
from .tokenize import Token
from .vocab import (
    MONTH_NAMES,
    ParseOptions,
    issue_suffix_set,
    single_letter_suffix_set,
)

_MAX_DIGITS = 12  # numeric tokens longer than this stay title content

FRACTION_GLYPHS: dict[str, Fraction] = {
    "½": Fraction(1, 2),
    "¼": Fraction(1, 4),
    "¾": Fraction(3, 4),
}

_D = r"\d{1,%d}" % _MAX_DIGITS
RE_PLAIN = re.compile(rf"^{_D}$")
RE_DECIMAL = re.compile(rf"^\d{{0,{_MAX_DIGITS}}}\.\d{{1,{_MAX_DIGITS}}}$")
RE_NEGATIVE = re.compile(rf"^-{_D}(?:\.\d{{1,{_MAX_DIGITS}}})?$")
RE_FRACTION = re.compile(rf"^(\d{{0,{_MAX_DIGITS}}}(?:\.\d{{0,{_MAX_DIGITS}}})?)([½¼¾])$")
RE_GLUED_SUFFIX = re.compile(rf"^({_D})([A-Za-z][A-Za-z']{{0,14}})!?$")
RE_DASH_SUFFIX = re.compile(rf"^({_D})-([A-Za-z]{{1,14}})!?$")
RE_DOTTED_SUFFIX = re.compile(rf"^({_D})\.([A-Za-z][A-Za-z']{{0,14}})!?$")
RE_RANGE = re.compile(rf"^(c?)({_D}(?:\.\d{{1,4}})?)\s?[-/]\s?({_D}(?:\.\d{{1,4}})?)$", re.IGNORECASE)
RE_YEAR = re.compile(r"^\d{4}$")
RE_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$")
RE_YEAR_RANGE = re.compile(r"^(\d{4})\s?-\s?(\d{4})?$")
RE_OF_COUNT = re.compile(rf"^of\s{{1,4}}({_D}(?:\.\d{{1,4}})?)$", re.IGNORECASE)
RE_COVERS = re.compile(rf"^({_D})\s{{1,4}}covers?$", re.IGNORECASE)
RE_PAGE_PX = re.compile(r"^\d{2,5}px$", re.IGNORECASE)
RE_PAGE_CTC = re.compile(r"^\d{1,4}p\s{1,4}(?:ctc|c2c)$", re.IGNORECASE)
RE_VOL_GLUED = re.compile(rf"^v(?:ol(?:ume)?)?\.?({_D})$", re.IGNORECASE)

_ROMAN = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7,
    "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13,
    "xiv": 14, "xv": 15, "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20,
}


def to_fraction(text: str) -> Fraction | None:
    """Guarded exact conversion of a plain/decimal/negative numeric string."""
    try:
        if RE_PLAIN.match(text) or RE_DECIMAL.match(text) or RE_NEGATIVE.match(text):
            return Fraction(text)
    except (ValueError, ZeroDivisionError):  # pragma: no cover - regex-guarded
        return None
    return None


def roman_to_int(text: str) -> int | None:
    return _ROMAN.get(fold(text))


def plausible_year(value: int, reference_year: int, *, lower: int = 1900) -> bool:
    """Years more than one year beyond the reference stay title content."""
    return lower <= value <= reference_year + 1


def _is_valid_calendar_date(year: int, month: int, day: int) -> bool:
    """Pure Gregorian calendar validity (leap-year aware).

    Avoids ``datetime`` entirely so the parser keeps zero clock/stdlib-date
    imports (FRG-IMP-002 purity guard); the arithmetic is deterministic.
    """
    if not 1 <= month <= 12:
        return False
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days_in_month = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return 1 <= day <= days_in_month[month - 1]


def match_date(text: str, reference_year: int, *, lower: int = 1900) -> int | None:
    """Extract a year from bare-year / ISO / month-name date text.

    Six-digit tokens are *not* validated as %Y%m dates (they are plausible
    issue numbers, FRG-IMP-013).
    """
    text = text.strip()
    if RE_YEAR.match(text):
        y = int(text)
        return y if plausible_year(y, reference_year, lower=lower) else None
    m = RE_ISO_DATE.match(text)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        day = int(m.group(3)) if m.group(3) else 1
        # Calendar-invalid ISO dates (Feb 30, month 13) are not dates: the
        # token falls through to other classifications (FRG-IMP-013).
        if _is_valid_calendar_date(year, month, day) and plausible_year(
            year, reference_year, lower=lower
        ):
            return year
    parts = text.replace(",", " ").split()
    if len(parts) == 2:
        month_name, year_text = parts
        if fold(month_name) in MONTH_NAMES and RE_YEAR.match(year_text):
            y = int(year_text)
            if plausible_year(y, reference_year, lower=lower):
                return y
    return None


@dataclass(slots=True)
class Candidate:
    """An issue-number candidate with its stable token position."""

    index: int
    value: Fraction | None
    display: str
    suffix: str | None = None
    is_infinity: bool = False
    name: str | None = None
    anchored: bool = False  # claimed by a '#' token (its own '#', FRG-IMP-007)
    count_flagged: bool = False  # anchored by an (of N) marker
    is_range: bool = False
    range_end: Fraction | None = None


def _suffix_lookup(alpha: str, options: ParseOptions, *, glued: bool) -> str | None:
    up = fold(alpha).upper().rstrip("!")
    if up in issue_suffix_set(options):
        return up
    if glued and up in single_letter_suffix_set(options) and len(up) == 1:
        return up
    return None


def numeric_candidate(
    token: Token, options: ParseOptions, reference_year: int
) -> Candidate | None:
    """Build a candidate from a single WORD token, if it is issue-shaped.

    ``reference_year`` gives the parser a single notion of a plausible year so
    that dash-joined tokens (``2013-05``) are disambiguated date-vs-range with
    the same cutoff the rest of the pipeline uses (FRG-IMP-010/-013).
    """
    text = token.inner
    idx = token.index
    anchored = False
    if text.startswith("#") and len(text) > 1:
        anchored = True
        text = text[1:]
    if not text:
        return None

    if text == "∞":
        return Candidate(idx, None, "∞", is_infinity=True, anchored=anchored)

    m = RE_FRACTION.match(text)
    if m:
        base = m.group(1)
        value = FRACTION_GLYPHS[m.group(2)]
        if base and base != ".":
            base_val = to_fraction(base if not base.endswith(".") else base[:-1])
            if base_val is None:
                return None
            value = base_val + value
        return Candidate(idx, value, text, anchored=anchored)

    if RE_PLAIN.match(text) or RE_DECIMAL.match(text) or RE_NEGATIVE.match(text):
        # dotted decimals double as dotted-suffix carriers; plain decimal here
        value = to_fraction(text)
        if value is None:
            return None
        return Candidate(idx, value, text, anchored=anchored)

    m = RE_DOTTED_SUFFIX.match(text)
    if m:
        sfx = _suffix_lookup(m.group(2), options, glued=False)
        if sfx:
            value = to_fraction(m.group(1))
            if value is not None:
                return Candidate(
                    idx, value, f"{m.group(1)}.{sfx}", suffix=sfx, anchored=anchored
                )
        return None

    m = RE_GLUED_SUFFIX.match(text)
    if m:
        sfx = _suffix_lookup(m.group(2), options, glued=True)
        if sfx:
            value = to_fraction(m.group(1))
            if value is not None:
                return Candidate(
                    idx, value, f"{m.group(1)}{m.group(2).rstrip('!')}", suffix=sfx, anchored=anchored
                )
        return None

    m = RE_DASH_SUFFIX.match(text)
    if m:
        sfx = _suffix_lookup(m.group(2), options, glued=True)
        if sfx:
            value = to_fraction(m.group(1))
            if value is not None:
                return Candidate(
                    idx, value, f"{m.group(1)}-{m.group(2).rstrip('!')}", suffix=sfx, anchored=anchored
                )
        return None

    m = RE_RANGE.match(text)
    if m and match_date(text, reference_year=reference_year) is None:
        start = to_fraction(m.group(2))
        end = to_fraction(m.group(3))
        if start is not None and end is not None:
            return Candidate(
                idx, start, text, is_range=True, range_end=end, anchored=anchored
            )
        return None

    if anchored:  # pure-alpha named issue requires its '#' anchor
        if re.match(r"^[A-Za-z][A-Za-z']{0,24}$", text):
            return Candidate(idx, None, text, name=text)
    return None
