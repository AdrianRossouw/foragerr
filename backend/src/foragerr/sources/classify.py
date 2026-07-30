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
from a CBZ-shipped RPG sourcebook, so the operator owns a LIBRARY-WIDE list of
publisher names that force ``other`` whatever the formats say. A rule wins over
every format signal above (rule 0, evaluated first); matching is on the SHARED
folded key (:func:`foragerr.parser.normalize.matching_key`, FRG-IMP-005) so
"Modiphius Entertainment" and "modiphius  entertainment." are the same rule, plus
a trailing ``*`` for substring probes (see :class:`PublisherRuleSet`). The list
ships with a curated non-comic default set
(:data:`foragerr.config.DEFAULT_NON_COMIC_PUBLISHERS`), every entry removable.

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


@dataclass(frozen=True, slots=True)
class PublisherRuleSet:
    """The library-wide publisher rules, compiled once per sync (FRG-SRC-012).

    Two folded views, both keyed on :func:`~foragerr.parser.normalize.matching_key`
    (FRG-IMP-005, the ONE folding implementation): ``exact`` names and
    ``substrings`` probes. An entry ending in ``*`` becomes a substring probe
    (``Paizo*`` covers "Paizo Inc." and "Paizo Publishing"); every other entry
    matches the folded publisher exactly — the semantics the ComicVine ignore
    list (FRG-META-020) presents to the operator, over this fold rather than a
    bare ``casefold`` so a rule keeps ONE identity across storage and matching.

    The wildcard MUST be read off the raw entry: ``matching_key`` treats ``*`` as
    punctuation and folds it away, so a probe derived from the folded string
    alone could never be told from an exact name. A bare ``*`` folds to nothing
    and is dropped rather than matching every publisher.
    """

    exact: frozenset[str]
    substrings: tuple[str, ...]

    @classmethod
    def parse(cls, entries: Iterable[str] | None) -> "PublisherRuleSet":
        """Compile an iterable of raw rule entries. Blank/whitespace-only and
        punctuation-only entries fold away and are dropped, so an all-blank list
        is indistinguishable from no rules at all."""
        exact: set[str] = set()
        substrings: list[str] = []
        for entry in entries or ():
            if not isinstance(entry, str):
                continue
            rule = entry.strip()
            key = matching_key(rule)
            if not key:
                continue
            if rule.endswith("*"):
                substrings.append(key)
            else:
                exact.add(key)
        return cls(exact=frozenset(exact), substrings=tuple(sorted(set(substrings))))

    @classmethod
    def from_csv(cls, raw: str | None) -> "PublisherRuleSet":
        """Compile the comma-separated settings string
        (``Settings.non_comic_publishers``)."""
        return cls.parse(split_rules(raw))

    def __bool__(self) -> bool:
        return bool(self.exact or self.substrings)

    def matches(self, publisher: str | None) -> bool:
        """Whether ``publisher`` is ruled non-comic.

        A row with no publisher, or one whose name folds to nothing, can never be
        ruled out — there is nothing to match against."""
        if not publisher:
            return False
        key = matching_key(publisher)
        if not key:
            return False
        if key in self.exact:
            return True
        return any(probe in key for probe in self.substrings)


#: The compiled empty rule set — pure format-shape classification.
NO_PUBLISHER_RULES = PublisherRuleSet(exact=frozenset(), substrings=())


def split_rules(raw: str | None) -> list[str]:
    """Split the comma-separated rule string into trimmed, non-empty entries."""
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _as_rule_set(
    rules: "PublisherRuleSet | Sequence[str] | None",
) -> PublisherRuleSet:
    if isinstance(rules, PublisherRuleSet):
        return rules
    return PublisherRuleSet.parse(rules)


def classify(
    options: list[DownloadOption],
    *,
    publisher: str | None = None,
    publisher_rules: "PublisherRuleSet | Sequence[str] | None" = None,
) -> str:
    """Classify a subproduct's download options as ``comic`` or ``other``.

    See the module docstring for the exact rule (FRG-SRC-003 design decision 4).

    ``publisher`` + ``publisher_rules`` apply the library-wide rule list
    (FRG-SRC-012): a rule match forces ``other`` ahead of every format signal.
    A raw sequence of entries is compiled on the spot; a sync passes the
    :class:`PublisherRuleSet` it compiled once for the whole run. Both default to
    "no rules", so the pure format-shape classification stands untouched.
    """
    if _as_rule_set(publisher_rules).matches(publisher):
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
