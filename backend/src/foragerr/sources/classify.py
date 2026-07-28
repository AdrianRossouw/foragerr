"""Comic-vs-other classification of Humble subproducts (FRG-SRC-003).

The finalized classification rule (design decision 4, recorded in design.md
Open Questions), applied to the parsed download options of one subproduct:

1. Consider only download options whose Humble ``platform == "ebook"`` — this
   narrows to books/comics and excludes games, audio, software, etc.
2. Collect each option's *format token* from its label (``name``) and the file
   extension of its download URL (``url.web``), uppercased.
3. **Comic archive formats** — ``CBZ``, ``CBR``, ``CB7``, ``CBT`` — are an
   unambiguous comic signal: any present ⇒ ``comic``.
4. Otherwise, a ``PDF`` with **no** prose format (``EPUB``, ``MOBI``, ``AZW3``)
   alongside it ⇒ ``comic`` (covers PDF-only OGNs / artbooks). A ``PDF`` that
   ships *with* a prose format is a prose ebook ⇒ ``other``.
5. Everything else (prose ebooks, or any non-``ebook`` platform) ⇒ ``other``.

**Publisher rules (FRG-SRC-012).** Format shape alone cannot tell a CBZ comic
from a CBZ-shipped RPG sourcebook, so the operator owns a per-source list of
publisher names that force ``other`` whatever the formats say. A rule wins over
every format signal above (rule 0, evaluated first); matching is on the SHARED
folded key (:func:`foragerr.parser.normalize.matching_key`, FRG-IMP-005) so
"Modiphius Entertainment" and "modiphius  entertainment." are the same rule.
The list ships EMPTY — a source with default settings classifies exactly as it
did before this change.

Non-comic items are retained as ``other`` and shown on demand — never dropped —
so a misclassification is discoverable and reclassifiable (FRG-SRC-003).

**Preferred grabbable format** (interim: prefer CBZ, per the format-preference
direction 2026-07-11): among the comic formats present, ``CBZ`` → ``CBR`` →
``CB7`` → ``CBT`` → ``PDF``. This is the copy whose md5/size/filename ride on the
entitlement row for the grab; the full option list is retained regardless.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from foragerr.parser.normalize import matching_key

#: The Humble download platform that narrows to books/comics (humble-api.md).
EBOOK_PLATFORM = "ebook"

#: Comic-archive format tokens — an unambiguous comic signal.
COMIC_ARCHIVE_FORMATS = ("CBZ", "CBR", "CB7", "CBT")

#: Prose ebook format tokens — presence alongside a bare PDF marks prose.
PROSE_FORMATS = frozenset({"EPUB", "MOBI", "AZW3"})

#: Grab-preference order among comic-eligible formats (interim: prefer CBZ).
PREFERRED_FORMAT_ORDER = ("CBZ", "CBR", "CB7", "CBT", "PDF")


@dataclass(frozen=True, slots=True)
class DownloadOption:
    """One parsed, comic-relevant download option of a subproduct.

    ``format`` is the uppercased format token; ``platform`` is the Humble
    platform (``ebook`` for the options that reach classification). The signed
    ``url.web`` is deliberately absent — it is time-limited and re-fetched fresh
    at grab time (design decision 8), never stored on the row.
    """

    format: str
    platform: str
    md5: str | None
    file_size: int | None
    filename: str | None


def _ebook_formats(options: list[DownloadOption]) -> set[str]:
    """The set of format tokens among the ``ebook``-platform options."""
    return {
        opt.format
        for opt in options
        if opt.platform == EBOOK_PLATFORM and opt.format
    }


def folded_publisher_rules(rules: Iterable[str] | None) -> frozenset[str]:
    """The operator's publisher rules as folded keys (FRG-SRC-012).

    Blank/whitespace-only entries fold away and are dropped, so an empty or
    all-blank list is indistinguishable from no rules at all."""
    if not rules:
        return frozenset()
    folded = {matching_key(rule) for rule in rules if isinstance(rule, str)}
    return frozenset(key for key in folded if key)


def publisher_is_ruled_out(
    publisher: str | None, rules: Iterable[str] | None
) -> bool:
    """Whether ``publisher`` matches one of the operator's rules (FRG-SRC-012).

    Matching is on the shared folded key, so casing, punctuation, and article
    noise never decide it. A row with no publisher can never be ruled out (there
    is nothing to match), and an empty rule list always answers ``False``."""
    if publisher is None:
        return False
    folded_rules = (
        rules
        if isinstance(rules, frozenset)
        else folded_publisher_rules(rules)
    )
    if not folded_rules:
        return False
    key = matching_key(publisher)
    return bool(key) and key in folded_rules


def classify(
    options: list[DownloadOption],
    *,
    publisher: str | None = None,
    publisher_rules: Sequence[str] | frozenset[str] | None = None,
) -> str:
    """Classify a subproduct's download options as ``comic`` or ``other``.

    See the module docstring for the exact rule (FRG-SRC-003 design decision 4).

    ``publisher`` + ``publisher_rules`` apply the operator's per-source rule
    list (FRG-SRC-012): a folded-key match forces ``other`` ahead of every
    format signal. Both default to "no rules", so the pure format-shape
    classification is unchanged for a source with default settings.
    """
    if publisher_is_ruled_out(publisher, publisher_rules):
        return "other"
    formats = _ebook_formats(options)
    if not formats:
        return "other"
    if any(fmt in formats for fmt in COMIC_ARCHIVE_FORMATS):
        return "comic"
    if "PDF" in formats and not (formats & PROSE_FORMATS):
        return "comic"
    return "other"


def preferred_option(options: list[DownloadOption]) -> DownloadOption | None:
    """The preferred grabbable comic option, or ``None`` if the item has none.

    Follows :data:`PREFERRED_FORMAT_ORDER` over the ``ebook``-platform options.
    Only meaningful for a ``comic`` item; an ``other`` item returns ``None`` (its
    prose formats are still retained in the full option list).
    """
    ebook_options = [
        opt for opt in options if opt.platform == EBOOK_PLATFORM and opt.format
    ]
    for fmt in PREFERRED_FORMAT_ORDER:
        for opt in ebook_options:
            if opt.format == fmt:
                return opt
    return None
