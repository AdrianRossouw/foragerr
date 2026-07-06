"""Token-based naming engine + default templates (FRG-PP-009, FRG-PP-010).

A dependency-free leaf (imports only :mod:`foragerr.security.paths`) so both the
importer (``foragerr.importer.renamer`` re-exports everything here unchanged) and
the config model (``foragerr.config``, which validates naming templates) can share
one implementation without importing the whole ``importer`` package — importing
``importer`` from ``config`` would form a cycle (``config`` → ``importer`` →
``downloads`` → … → ``config``). The engine itself is pure and has no importer,
db, or downloads dependency, so it lives here safely.

One template implementation drives both file names and folder paths (design
decision 7). A template is literal text interleaved with:

- **tokens** — ``{Series Title}``, ``{Issue Number:000}``, ``{Year}``,
  ``{Release Group}``, ``{Classification}``, ``{Booktype}``, ``{Volume}``,
  ``{Publisher}``, ``{Issue Title}``, ``{Series CleanTitle}``, ``{IssueId}`` —
  resolved from a :class:`RenameFields` value. A ``:pad`` suffix
  (``{Issue Number:000}``) zero-pads the integer part decimal-safely, so
  ``15.5`` renders ``015.5`` and ``1.MU`` renders ``001.MU``. The **case** of
  the token name's letters controls the output case: an all-lower token name
  lowercases its value, an all-upper name uppercases it, mixed/title case leaves
  the source case untouched.
- **optional groups** — ``[ … ]``. The brackets are literal output (so the
  ``[__{IssueId}__]`` issue-id tag round-trips through the parser's
  ``[__id__]`` reader), *and* the entire bracketed span is dropped when it
  contains at least one token and every token in it resolved empty. A bracketed
  span with no tokens is plain literal text and is always kept.

File rendering (:func:`render_filename`) additionally applies an
illegal-character replacement policy and byte-aware truncation to a path-length
limit, and honours a disable switch (renaming off ⇒ keep the original name).
Folder rendering delegates per-segment safety to
:func:`foragerr.security.paths.safe_path_component` (single ownership,
FRG-SEC-004) rather than duplicating a second sanitizer, so it never applies the
file policy — this is also what keeps :func:`render_series_folder` byte-for-byte
identical to change-3's fixed series-folder template (FRG-PP-010 / SER-008).

The **round-trip contract** (FRG-PP-009): every name this engine renders from a
real issue identity re-parses, via the single change-2 parser, to the same
series matching key and issue ordering key. Property-tested in
``tests/importer/test_renamer_roundtrip.py`` over the parser corpus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from foragerr.security.paths import safe_path_component

# --- default templates -------------------------------------------------------

#: M1 default file template (design decision 7). ``({Year})`` is intentionally
#: not optional (a library issue always has a series start year); the issue-id
#: tag is optional (rescan-sourced files carry none).
DEFAULT_FILE_TEMPLATE = "{Series Title} {Issue Number:000} ({Year}) [__{IssueId}__]"

#: M1 default folder template — change-3's fixed ``{title} ({year})`` shape,
#: now owned here (SER-008 transfer, FRG-PP-010).
DEFAULT_FOLDER_TEMPLATE = "{Series Title} ({Year})"

#: Folder template used when the series has no known start year (change-3
#: parity: the year suffix is omitted entirely rather than rendered empty).
FOLDER_TEMPLATE_NO_YEAR = "{Series Title}"

#: Default byte ceiling for a single rendered filename component (incl. ext).
DEFAULT_MAX_FILENAME_BYTES = 255


# --- token vocabulary --------------------------------------------------------

#: Casefolded, whitespace-collapsed token name → canonical field key.
_TOKEN_ALIASES: dict[str, str] = {
    "series title": "series_title",
    "series cleantitle": "series_cleantitle",
    "cleantitle": "series_cleantitle",
    "volume": "volume",
    "year": "year",
    "issue": "issue",
    "issue number": "issue",
    "issue title": "issue_title",
    "classification": "classification",
    "booktype": "booktype",
    "release group": "release_group",
    "issueid": "issue_id",
    "issue id": "issue_id",
    "publisher": "publisher",
}


@dataclass(frozen=True, slots=True)
class RenameFields:
    """The resolved token values for one issue (all pre-stringified or ``None``).

    ``None`` (or empty string) marks an absent field, so an optional group
    referencing only absent fields is dropped.
    """

    series_title: str | None = None
    series_cleantitle: str | None = None
    volume: str | None = None
    year: str | None = None
    issue: str | None = None
    issue_title: str | None = None
    classification: str | None = None
    booktype: str | None = None
    release_group: str | None = None
    issue_id: str | None = None
    publisher: str | None = None

    def as_map(self) -> dict[str, str | None]:
        return {
            "series_title": self.series_title,
            "series_cleantitle": self.series_cleantitle,
            "volume": self.volume,
            "year": self.year,
            "issue": self.issue,
            "issue_title": self.issue_title,
            "classification": self.classification,
            "booktype": self.booktype,
            "release_group": self.release_group,
            "issue_id": self.issue_id,
            "publisher": self.publisher,
        }


# --- lexing ------------------------------------------------------------------

_GROUP_RE = re.compile(r"\[([^\[\]]*)\]")
_TOKEN_RE = re.compile(r"\{([^{}:]+)(?::([^{}]*))?\}")
_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WS_RE = re.compile(r"[ \t]+")


def _canonical(name: str) -> str:
    return " ".join(name.strip().split()).casefold()


def _apply_case(raw_name: str, value: str) -> str:
    """Token-name case controls output case (FRG-PP-009)."""
    if not value:
        return value
    letters = [c for c in raw_name if c.isalpha()]
    if not letters:
        return value
    if all(c.isupper() for c in letters):
        return value.upper()
    if all(c.islower() for c in letters):
        return value.lower()
    return value


def _apply_pad(value: str, pad: str) -> str:
    """Zero-pad the integer part decimal-safely (``15.5`` → ``015.5``)."""
    width = len(pad)
    if width == 0:
        return value
    neg = value.startswith("-")
    core = value[1:] if neg else value
    int_part, dot, frac = core.partition(".")
    if not int_part.isdigit():
        return value  # named/suffix issue with no numeric integer part
    padded = int_part.zfill(width)
    result = f"{padded}.{frac}" if dot else padded
    return f"-{result}" if neg else result


def _render_segment(text: str, fmap: dict[str, str | None], empties: list[bool]) -> str:
    """Substitute every token in ``text``; record per-token emptiness."""

    def repl(m: re.Match[str]) -> str:
        key = _TOKEN_ALIASES.get(_canonical(m.group(1)))
        raw = fmap.get(key) if key is not None else None
        val = "" if raw is None else str(raw)
        if m.group(2) is not None and val:
            val = _apply_pad(val, m.group(2))
        val = _apply_case(m.group(1), val)
        empties.append(val == "")
        return val

    return _TOKEN_RE.sub(repl, text)


def render(template: str, fields: RenameFields) -> str:
    """Render ``template`` against ``fields`` (tokens + optional groups)."""
    fmap = fields.as_map()
    out: list[str] = []
    pos = 0
    for gm in _GROUP_RE.finditer(template):
        out.append(_render_segment(template[pos : gm.start()], fmap, []))
        inner_empties: list[bool] = []
        inner = _render_segment(gm.group(1), fmap, inner_empties)
        if inner_empties and all(inner_empties):
            pass  # bracketed span with tokens, all empty → drop it entirely
        else:
            out.append(f"[{inner}]")
        pos = gm.end()
    out.append(_render_segment(template[pos:], fmap, []))
    return "".join(out)


# --- file names --------------------------------------------------------------


def _normalize_ext(ext: str | None) -> str:
    if not ext:
        return ""
    return ext if ext.startswith(".") else f".{ext}"


def _truncate_bytes(text: str, max_bytes: int) -> str:
    """Truncate ``text`` so its UTF-8 length ≤ ``max_bytes`` without splitting a
    multibyte character."""
    if max_bytes <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", "ignore").rstrip(" .")


def _render_body(template: str, fields: RenameFields, replace_illegal: bool) -> str:
    """Render + illegal-char-replace + whitespace-collapse a file basename."""
    body = render(template, fields)
    if replace_illegal:
        body = _ILLEGAL_RE.sub(" ", body)
    return _WS_RE.sub(" ", body).strip().strip(" .")


def _shrink_series_title_to_fit(
    fields: RenameFields,
    template: str,
    replace_illegal: bool,
    budget: int,
) -> RenameFields:
    """Trim only ``series_title`` until the rendered basename fits ``budget`` bytes.

    Truncating the whole rendered string from the right would drop the trailing
    round-trip-critical ``[__{IssueId}__]`` identity tag (and the issue number),
    making a re-imported file unrecoverable (FRG-PP-009). Instead we shrink the
    one unbounded *variable* token — the series title — via a binary search on
    the largest title prefix that still fits, so the issue number, year, and id
    tag always survive.
    """
    title = fields.series_title or ""
    lo, hi, best = 0, len(title), ""
    while lo <= hi:
        mid = (lo + hi) // 2
        trial = title[:mid].rstrip()
        body = _render_body(template, replace(fields, series_title=trial), replace_illegal)
        if len(body.encode("utf-8")) <= budget:
            best = trial
            lo = mid + 1
        else:
            hi = mid - 1
    return replace(fields, series_title=best)


def render_filename(
    fields: RenameFields,
    *,
    template: str = DEFAULT_FILE_TEMPLATE,
    ext: str | None = "",
    enabled: bool = True,
    original: str | None = None,
    max_bytes: int = DEFAULT_MAX_FILENAME_BYTES,
    replace_illegal: bool = True,
) -> str:
    """Render one file's basename (FRG-PP-009).

    With ``enabled=False`` the ``original`` filename is returned unchanged (the
    disable switch). Illegal filename characters are replaced with a space and
    whitespace is collapsed; the result is byte-truncated so basename+extension
    stays within ``max_bytes``.
    """
    if not enabled:
        if original is None:
            raise ValueError("render_filename(enabled=False) needs the original name")
        return original
    ext_str = _normalize_ext(ext)
    budget = max_bytes - len(ext_str.encode("utf-8"))
    body = _render_body(template, fields, replace_illegal)
    if len(body.encode("utf-8")) > budget:
        # Over the byte ceiling: shrink the variable series title so the trailing
        # id tag + issue number survive (FRG-PP-009), rather than lopping the
        # whole basename from the right (which would drop the identity tag).
        body = _render_body(
            template,
            _shrink_series_title_to_fit(fields, template, replace_illegal, budget),
            replace_illegal,
        )
        # Safety net for a pathological budget with no title left to trim: a
        # last-resort byte truncation keeps the name within the filesystem limit.
        if len(body.encode("utf-8")) > budget:
            body = _truncate_bytes(body, budget)
    return body + ext_str


# --- folders -----------------------------------------------------------------


def render_folder_segments(
    fields: RenameFields, *, template: str = DEFAULT_FOLDER_TEMPLATE
) -> list[str]:
    """Render a folder template into path segments for :func:`safe_join`.

    The rendered template is split on ``/`` into segments; each is handed to the
    caller (the pipeline) which joins them under the library root via
    :func:`foragerr.security.paths.safe_join`, so per-segment sanitization is
    owned there (FRG-SEC-004) and not duplicated in the renamer. Empty segments
    are dropped.
    """
    rendered = render(template, fields)
    rendered = _WS_RE.sub(" ", rendered)
    return [seg.strip() for seg in rendered.split("/") if seg.strip()]


def render_series_folder(title: str, start_year: int | None) -> str:
    """Render the series-folder name — change-3's fixed template, now owned by
    this engine (SER-008 transfer, FRG-PP-010).

    Byte-for-byte identical to change-3's ``series_folder_name``: the title is
    reduced by :func:`safe_path_component` (single sanitizer) and the
    ``({year})`` suffix is dropped entirely when the year is unknown. No
    file-level illegal-character policy is applied here — path-segment safety is
    :func:`safe_join`'s job — so existing rows keep the same on-disk name.
    """
    safe_title = safe_path_component(title)
    fields = RenameFields(
        series_title=safe_title,
        year=None if start_year is None else str(start_year),
    )
    template = DEFAULT_FOLDER_TEMPLATE if start_year is not None else FOLDER_TEMPLATE_NO_YEAR
    return _WS_RE.sub(" ", render(template, fields)).strip()


__all__ = [
    "DEFAULT_FILE_TEMPLATE",
    "DEFAULT_FOLDER_TEMPLATE",
    "DEFAULT_MAX_FILENAME_BYTES",
    "FOLDER_TEMPLATE_NO_YEAR",
    "RenameFields",
    "render",
    "render_filename",
    "render_folder_segments",
    "render_series_folder",
]
