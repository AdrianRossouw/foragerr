"""Sanitization of untrusted ComicVine strings (FRG-META-014, FRG-NFR-012).

ComicVine's name/alias/description fields are user-editable wiki content and
are therefore untrusted input (RISK-011, RISK-014). :func:`sanitize_cv_text`
is the single ingest sanitizer every ComicVine-originated string passes
through inside :mod:`foragerr.metadata` before it is persisted, rendered,
logged, or used to steer a downstream query — nothing outside this module
should ever see raw ComicVine HTML.

The sanitizer, in order:

1. reduces HTML to its text nodes (``<script>``/``<style>`` bodies dropped
   entirely) using the stdlib :mod:`html.parser` — no third-party dependency;
2. strips ANSI escape sequences and C0/DEL control characters so control
   codes and forged CR/LF log lines can never reach logs (RISK-014);
3. removes Unicode bidirectional-override and zero-width/invisible format
   characters (RLO/LRO, isolates, ZWSP/ZWJ, word-joiner, BOM) — the same
   forged-ordering hazard class as CR/LF, they let hostile wiki text visually
   spoof or reverse the rendered string (Trojan-Source, RISK-011/014) and are
   never legitimate content in a plain-text field;
4. collapses all whitespace runs to single spaces and trims;
5. caps the length at :data:`MAX_TEXT_LENGTH`.

The result is plain text intended to be rendered as ``textContent`` / encoded
on output — never re-interpreted as markup. Note this strips *tags*, not literal
angle-bracket prose: HTML entities are decoded (``&lt;`` -> ``<``), so
bracket-looking text can remain — output safety rests on rendering it as text,
not on this function guaranteeing tag-free output.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

#: Documented maximum length of any sanitized ComicVine string. Longer inputs
#: are truncated (FRG-NFR-012 "truncated to the documented length cap").
MAX_TEXT_LENGTH = 10_000

#: Tag bodies discarded wholesale — their text is never content.
_DROP_TAGS = frozenset({"script", "style"})

#: Tags whose boundaries imply a word/line break, so stripping them must not
#: fuse adjacent words (``<p>a</p><p>b</p>`` -> ``a b``, not ``ab``).
_SPACING_TAGS = frozenset(
    {
        "p", "br", "div", "li", "tr", "td", "th", "ul", "ol", "table",
        "blockquote", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6",
    }
)

# ANSI/VT escape sequences (CSI and friends) — removed before logging (RISK-014).
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")
# C0 control chars and DEL, excluding the whitespace chars collapsed below.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Unicode bidi-override / isolate controls and zero-width / invisible format
# characters. None are legitimate in a plain-text CV field; left in, they enable
# Trojan-Source-style visual reordering/spoofing of the rendered string
# (RISK-011/014). ARABIC LETTER MARK (061C), bidi embeds/overrides/isolates
# (200E-200F, 202A-202E, 2066-2069), zero-width space/joiners (200B-200D),
# invisible math operators (2060-2064), and the BOM/ZWNBSP (FEFF).
_BIDI_INVISIBLE_RANGES = (
    (0x061C, 0x061C),  # ARABIC LETTER MARK
    (0x200B, 0x200F),  # ZWSP, ZWNJ, ZWJ, LRM, RLM
    (0x202A, 0x202E),  # LRE, RLE, PDF, LRO, RLO
    (0x2060, 0x2064),  # word joiner + invisible math operators
    (0x2066, 0x2069),  # LRI, RLI, FSI, PDI
    (0xFEFF, 0xFEFF),  # ZWNBSP / BOM
)
_BIDI_INVISIBLE_RE = re.compile(
    "[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in _BIDI_INVISIBLE_RANGES) + "]"
)
_WS_RE = re.compile(r"\s+")


class _TextExtractor(HTMLParser):
    """Collects text nodes, dropping ``<script>``/``<style>`` bodies and
    inserting a space at block-tag boundaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._drop_depth = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _DROP_TAGS:
            self._drop_depth += 1
        elif tag in _SPACING_TAGS:
            self._parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: object) -> None:
        if tag in _SPACING_TAGS:
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_TAGS and self._drop_depth:
            self._drop_depth -= 1
        elif tag in _SPACING_TAGS:
            self._parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._drop_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _strip_html(value: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception:  # hostile/malformed markup must never raise on ingest
        return value
    return parser.text()


def sanitize_cv_text(value: str | None) -> str | None:
    """Reduce an untrusted ComicVine string to safe plain text.

    Returns ``None`` for a ``None`` input or when nothing printable remains
    (so an all-HTML or all-control-character field becomes ``None`` rather
    than an empty sentinel string). Never raises on hostile input.
    """
    if value is None:
        return None
    text = _strip_html(value)
    text = _ANSI_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text = _BIDI_INVISIBLE_RE.sub("", text)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH].rstrip()
    return text or None
