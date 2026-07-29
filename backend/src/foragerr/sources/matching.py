"""Server-side proposed-match computation for new entitlements (FRG-SRC-010).

When a sync lands a NEW comic entitlement it carries no match. This module
computes a *proposed* match server-side so the review UI can render a suggestion
and the auto-sync path (when ON) can act on a confident one. It reuses the
existing relevance machinery rather than inventing a second ranker:

* :func:`foragerr.metadata.search.name_similarity` — the SequenceMatcher-over-
  ``matching_key`` score (FRG-META-015), the same primitive the ComicVine
  search/suggest ranking sorts by;
* :func:`foragerr.parser.normalize.matching_key` — the single title-folding
  implementation (FRG-IMP-005), used both by ``name_similarity`` and directly by
  the token-overlap gate below;
* :func:`foragerr.library.booktype.detect_series_booktype` — the ONE
  collected-edition cue vocabulary (``parser.vocab.BOOKTYPE_CUES``), reused for
  the trade re-rank so this module never grows a second cue list.

**ComicVine is the matching universe (FRG-SRC-010).** Candidates come from
``cv_client.suggest_series`` — the catalog, not the operator's shelf. The
library is an *overlay*, not a second ranking pool: after the CV candidates are
gated, scored and ranked, each survivor whose ``cv_volume_id`` is already
present as a library series is re-stamped ``kind="library"`` with that
``series_id``, so accepting it MATCHES in one action; a candidate not in the
library stays ``kind="comicvine"`` and accepting it ADDS-and-matches in one
action (the FRG-SRC-008 seam handles both). This is the inversion of the old
library-first two-pool strategy, whose small-library ranking is what let
"Distant Amber Signal" propose itself for "Nobody is Guarding the Lighthouse
Vol. 8".

**The overlay is applied strictly AFTER gating and ranking.** It carries a
*display* title (the operator's local series title, which may legitimately
diverge from the catalog's — ``"Vane (2012)"`` locally for CV's ``"Vane"``), and
a display title is not evidence about catalog identity. Feeding it into the
token gate or the similarity score would let a local rename discard a correct
in-library candidate, and would leak shelf-local metadata into a gate that is
supposed to be CV-first. So the gate, the floor, the similarity and the trade
re-rank all read the ComicVine title; the overlay then re-stamps
``kind``/``series_id``/title on the ranked survivors, changing the ACTION shape
and the label, never the verdict.

**Strip-then-score (FRG-SRC-010, amended).** Everything that decides identity —
the token gate, the similarity, the floor and the AUTO comparison — runs on the
*stripped* fold: the shared ``matching_key`` fold with edition boilerplate
removed (volume/book/part/issue/number designators, bare numerals and ordinals,
and the shared collected-edition cue vocabulary). Boilerplate is what almost
every store title has in common, so scoring on the raw fold made it identity
evidence in both directions:

* it ADMITTED strangers — ``"Vane Vol. 1"`` and ``"Argent Vol. 1"`` share the
  ``vol``/``1`` tokens, so the gate passed a candidate with nothing in common,
  and ``"The Vants Vol. 1"`` vs ``"The Vints Vol. 1"`` scored 0.91 (over the
  auto-accept bar) off two shared boilerplate tokens and a one-letter difference;
* it DISCARDED the right answer — ``"Vane Volume 1"`` scored ComicVine's exact
  ``"Vane"`` at 0.4706 (floored out) while the unrelated ``"Vane of the Sunken
  Reef"`` survived at 0.5625, purely because the decorated query is long and the
  correct title is short.

Stripped, those become ``vane`` vs ``vane`` (1.0), ``vane`` vs ``argent`` (no
shared token — gated), and ``vants`` vs ``vints`` (no shared token either).

**Containment guard.** Length-asymmetric similarity still buries a short exact
title under a long decorated one (``"Ashclaw"`` scores 0.4118 against
``"Ashclaw Omnibus Volume 1: Fang of Devastation"`` stripped to ``ashclaw fang
of devastation``). So a candidate whose stripped title occurs as a contiguous
token run inside the stripped query is never floored out: it scores at least
:data:`MAX_CONTAINMENT_CONFIDENCE` — deliberately BELOW
:data:`AUTO_MATCH_THRESHOLD`, because containment proves plausibility (this
purchase is decorated) and not identity (``"Argent"`` is contained in
``"Argent and Shale"`` too). An exact stripped-title equality still scores 1.0,
so a real exact match always outranks a containment rescue.

**Token-overlap gate.** A candidate is discarded BEFORE similarity ranking
unless its STRIPPED fold shares at least one substantive token with the
stripped query term (articles are already dropped by the fold; boilerplate is
dropped by the strip). Character-level similarity alone is not evidence of
identity — the repro pair above scores 0.3673 with zero shared tokens — so the
gate, not the floor, is what makes that class impossible.
:data:`PROPOSE_MIN_SIMILARITY` then applies to the gated survivors.

**Trade re-rank (soft).** When the store title is trade-SHAPED — it carries a
collected-edition cue OR a volume/book-ordinal shape (``"Vane Vol. 1"``,
``"Glasswing Book One"``, ``"Ashclaw Omnibus Volume 1"``) — candidates carrying
a collected cue are boosted and bare ones demoted, so a trade-shaped purchase
proposes the collected-edition volume rather than the singles line. ComicVine
carries no book-type field, so name cues are the only signal available and the
re-rank must stay soft: it reorders, it never excludes, and it never alters a
candidate's reported ``confidence``. The import-time trade guard (FRG-PP-022
guard 1) remains the backstop.

**No-key fallback.** With no ``cv_client`` (no ComicVine key configured) the
computation degrades to library-only ranking — same gate, same floor — and says
so: the proposal carries ``universe="library-fallback"`` instead of
``"comicvine"``, so the UI never presents a shelf-local guess as a catalog
verdict.

**No plausible match is a VERDICT, not a silence (FRG-SRC-010).** When the
computation actually ran — ComicVine answered, or the no-key fallback ranked the
library — and nothing survived gate + floor, the result is an explicit
*no-plausible-match marker*: a :class:`ProposedMatch` with no ``best``, no
candidates, and ``verdict="no-plausible-match"``. The caller stores it, so the
row is distinguishable from one whose proposal was never computed (NULL =
deferred/retryable). It remains a verdict about the *automatic* computation
only, never a terminal state: the per-row ComicVine search (FRG-UI-039) is
present on every reviewable row, and the marker is not acceptable (accepting it
raises the same "no proposed match" 422 a NULL row does).

``None`` is now reserved for "the computation could NOT run": ComicVine was
consulted and failed (a 500, a transport error), so no verdict exists and the
row stays NULL/retryable for the next sync. Freezing a marker on an upstream
blip would be the same hazard as freezing a fallback proposal on a budget hit.

**Budget-aware (FRG-META-016).** A :class:`ComicVineBudgetExhausted` mid-batch
is never swallowed into a bad proposal: it propagates so the caller leaves the
entitlement ``new`` with a NULL proposal — a later sync retries. It never
degrades into a library-only proposal or a no-match marker: both would freeze
the row and the deferred CV lookup would never happen. Deferral semantics are
unchanged from the library-first implementation. CV is consulted at most once
per new comic entitlement.

**Auto-match threshold.** ``AUTO_MATCH_THRESHOLD = 0.85``: the confidence at/above
which the opt-in auto-sync path (FRG-SRC-004) may accept-and-download without
operator review. It is a ``name_similarity`` value — a normalized-title
SequenceMatcher ratio in ``[0, 1]`` — chosen from the fixtures: ``"Synthetic
Hero #1"`` folds to ``synthetic hero 1`` which scores ~0.93 against a
``"Synthetic Hero"`` candidate (clears the bar), while the collected edition
``"...The Collected Edition Vol. 1 (collects #1-6)"`` folds to a long token run
that scores ~0.54 against the same name (correctly withheld — a trade must not
silently auto-file into the singles run). 0.85 sits in the gap: high enough that
a different series (a few shared words) never clears it, low enough that
punctuation/casing/spacing noise on the true title does. Below the bar an item
still gets a *proposed* match for the UI; it just stays in review until the
operator acts. The threshold is compared against the raw similarity, so the
trade re-rank below can never lift a candidate over it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from functools import lru_cache

from foragerr.library.booktype import detect_series_booktype
from foragerr.metadata.search import name_similarity
from foragerr.parser.normalize import matching_key
from foragerr.parser.vocab import DEFAULT_OPTIONS, booktype_cue_phrases

#: Confidence at/above which the opt-in auto-sync path may auto-accept (0..1).
AUTO_MATCH_THRESHOLD = 0.85

#: Floor below which no proposal is stored at all (a guess this weak is noise);
#: the entitlement stays ``new`` with a NULL proposal, surfaced as unmatched.
#: Applied to the gated survivors, on the STRIPPED similarity (never the
#: re-ranked score) so the trade boost cannot smuggle a weak candidate over the
#: floor — and never against a candidate the containment guard rescued.
PROPOSE_MIN_SIMILARITY = 0.5

#: How many ranked candidates to retain in the stored proposal for the UI.
MAX_CANDIDATES = 3

#: Ceiling on the confidence a CONTAINMENT rescue may award (FRG-SRC-010).
#: A candidate saved by the containment guard — its stripped title occurs whole
#: inside the stripped query — has proved that the store title *decorates* it,
#: which is evidence of plausibility, not of identity ("Argent" is contained in
#: "Argent and Shale"). Deliberately below :data:`AUTO_MATCH_THRESHOLD` so a
#: rescue always proposes-for-review and never accept-and-downloads, and below
#: the 1.0 an exact stripped-title equality earns so a real exact match always
#: outranks a rescue.
MAX_CONTAINMENT_CONFIDENCE = 0.8

#: Ordering-only multiplier for the trade re-rank (FRG-SRC-010 / design D2).
#: When the store title carries a collected-edition cue, a candidate carrying a
#: collected cue sorts as ``confidence * TRADE_RERANK_BOOST`` and a bare
#: candidate as ``confidence / TRADE_RERANK_BOOST`` — an effective ratio of
#: ``1.25 ** 2 = 1.5625`` between the two shapes. Sized to flip realistic
#: near-ties (the fixture pair 0.9091 singles vs 0.8571 collected flips to
#: 0.7273 vs 1.0714) without letting a genuinely unrelated collected edition
#: overtake a strong exact-title candidate. It NEVER touches the stored
#: ``confidence``, the floor, or :data:`AUTO_MATCH_THRESHOLD`.
TRADE_RERANK_BOOST = 1.25

#: ``ProposedMatch.universe`` values: which catalog the ranking actually saw.
UNIVERSE_COMICVINE = "comicvine"
UNIVERSE_LIBRARY_FALLBACK = "library-fallback"

#: ``ProposedMatch.verdict`` for a computation that RAN and found nothing
#: plausible. Stored on the row so "computed, no match" is distinguishable from
#: "not computed yet" (NULL). A normal proposal carries ``verdict = None`` and
#: its serialized shape is unchanged.
VERDICT_NO_PLAUSIBLE_MATCH = "no-plausible-match"

_TRAILING_ISSUE = re.compile(r"\s*#\s*[0-9]+[a-z.]*\s*$", re.IGNORECASE)
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*$")

#: Generic edition/designator words stripped before scoring (FRG-SRC-010).
#:
#: The parser owns the two vocabularies that DO carry meaning —
#: :data:`foragerr.parser.vocab.BOOKTYPE_CUES` (collected-edition cues, reused
#: verbatim below via :func:`~foragerr.parser.vocab.booktype_cue_phrases`) and
#: the issue-suffix / edition-tag lists — but it owns no vocabulary of the bare
#: *structural* designators, because it reads them positionally from a filename
#: grammar (``scan_volumes`` matches ``vol``/``vol.``/``volume`` inline) rather
#: than as a word list. This is that missing list and nothing more: purely
#: structural words that name a slice of a series and never name a series.
#: It is deliberately NOT a second cue list — cue words come from the parser.
STRIP_DESIGNATORS: frozenset[str] = frozenset(
    {
        "vol",
        "vols",
        "volume",
        "volumes",
        "book",
        "books",
        "part",
        "parts",
        "issue",
        "issues",
        "chapter",
        "chapters",
        "number",
        "numbers",
        "no",
        "nos",
        "omnibus",
    }
)

#: Ordinal/cardinal words that spell out an edition's slice number
#: ("Glasswing Book One"). Bare digits are stripped by shape, not by list.
STRIP_ORDINAL_WORDS: frozenset[str] = frozenset(
    {
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "first",
        "second",
        "third",
        "fourth",
        "fifth",
        "sixth",
        "seventh",
        "eighth",
        "ninth",
        "tenth",
    }
)

#: ``1``, ``01``, ``1st``, ``2nd`` … — a bare slice number in any spelling.
_BARE_NUMERAL = re.compile(r"^\d+(?:st|nd|rd|th)?$")

#: The subset of :data:`STRIP_DESIGNATORS` that names a COLLECTION slice, and so
#: implies a trade shape when it carries an ordinal. Deliberately narrower than
#: the strip list: ``issue``/``chapter``/``number`` name a SINGLE, so "Issue 5"
#: must not re-rank collected editions to the top.
VOLUME_SHAPE_DESIGNATORS: frozenset[str] = frozenset(
    {"vol", "vols", "volume", "volumes", "book", "books", "part", "parts"}
)

#: A volume/book-ordinal SHAPE in the raw store title ("Vane Vol. 1",
#: "Glasswing Book One", "Ashclaw Omnibus Vol. 1") — trade-shaped even without
#: an explicit collected-edition cue (FRG-SRC-010, amended). BUILT from the sets
#: above rather than re-spelled, so the shape and the strip can never drift:
#: anything this detects is, by construction, boilerplate the strip removes.
_VOLUME_SHAPE = re.compile(
    r"\b(?:"
    + "|".join(sorted(VOLUME_SHAPE_DESIGNATORS, key=len, reverse=True))
    + r")\b\.?\s*(?:no\.?\s*)?(?:\d+|"
    + "|".join(sorted(STRIP_ORDINAL_WORDS))
    + r")\b",
    re.IGNORECASE,
)

#: The value :func:`trade_shape` reports for a bare volume/book-ordinal shape
#: (no explicit collected-edition cue). Only its truthiness is consumed.
TRADE_SHAPE_VOLUME_ORDINAL = "volume-ordinal"

#: Stripped designators that IMPLY a collected edition by themselves. "Omnibus"
#: is boilerplate to the similarity fold (both "Ashclaw" and "Ashclaw Omnibus"
#: strip to "ashclaw") but it is not in the parser's cue vocabulary — so
#: without this set neither side of the trade re-rank would see it, the two
#: volumes would tie on stripped similarity, and the wrong shape could win on
#: ordering. Whether "omnibus" belongs in the parser's BOOKTYPE_CUES proper is
#: banked as a parser-corpus question (it would change filename booktype
#: detection, FRG-IMP-016); this local set only informs the re-rank.
COLLECTED_STRIP_WORDS: frozenset[str] = frozenset({"omnibus"})


def _collected_shaped(title: str) -> bool:
    """Whether a title signals a collected edition for re-rank purposes:
    an explicit shared-vocabulary cue, or a stripped-but-collected word."""
    if detect_series_booktype(title) is not None:
        return True
    return any(tok in COLLECTED_STRIP_WORDS for tok in matching_key(title).split())


def query_term(human_name: str) -> str:
    """The store title reduced to a series-shaped query term.

    Drops a trailing issue token (``"Hero #1"`` → ``"Hero"``) and a trailing
    parenthetical (``"... (collects #1-6)"``) so the folded-title similarity
    keys off the series name, not the copy-specific suffix. Folding itself is
    ``name_similarity``'s job (``matching_key``) — this only trims obvious
    per-copy noise.

    The two trims are applied ALTERNATELY until the term stops shrinking,
    because either can uncover the other: ``"Ember (1992) #1"`` has a
    parenthetical that is not trailing until the ``#1`` is gone, and a single
    pass left it as ``"ember 1992"`` — a group key of its own, splitting a
    long single-title run's collapse group by print year (FRG-SRC-011).
    """
    term = human_name.strip()
    for _ in range(4):  # bounded: each round strictly shortens or stops
        shorter = _TRAILING_ISSUE.sub("", _PARENTHETICAL.sub("", term)).strip()
        if shorter == term:
            break
        term = shorter
    return term or human_name.strip()


@lru_cache(maxsize=4096)
def stripped_tokens(text: str | None) -> tuple[str, ...]:
    """The SUBSTANTIVE token run of a title (FRG-SRC-010, amended).

    The shared fold (:func:`~foragerr.parser.normalize.matching_key`) with
    edition boilerplate removed: the shared collected-edition cue phrases
    (:func:`~foragerr.parser.vocab.booktype_cue_phrases`, longest-first, matched
    as contiguous runs exactly as :mod:`foragerr.library.booktype` matches
    them), the structural designators of :data:`STRIP_DESIGNATORS`, spelled-out
    ordinals, and bare numerals.

    A title that is ENTIRELY boilerplate ("Volume 1") keeps its folded tokens
    rather than vanishing — same guard ``matching_key`` applies to an
    articles-only title. Without it every such title would fold to the empty
    token set and then gate-match nothing (or, worse, everything).
    """
    if not text:
        return ()
    key = matching_key(text)
    if not key:
        return ()
    tokens = key.split()
    remaining = _drop_cue_phrases(tokens)
    kept = [
        t
        for t in remaining
        if t not in STRIP_DESIGNATORS
        and t not in STRIP_ORDINAL_WORDS
        and not _BARE_NUMERAL.match(t)
    ]
    return tuple(kept) if kept else tuple(tokens)


def _drop_cue_phrases(tokens: list[str]) -> list[str]:
    """Remove the parser's collected-edition cue phrases, longest first."""
    for phrase, _booktype in booktype_cue_phrases(DEFAULT_OPTIONS):
        n = len(phrase)
        if n == 0 or n > len(tokens):
            continue
        i = 0
        while i <= len(tokens) - n:
            if tuple(tokens[i : i + n]) == phrase:
                tokens = tokens[:i] + tokens[i + n :]
            else:
                i += 1
    return tokens


def stripped_key(text: str | None) -> str:
    """:func:`stripped_tokens` re-joined — the string the similarity scores."""
    return " ".join(stripped_tokens(text))


def group_key(human_name: str) -> str:
    """The review screen's collapse key for a store title (FRG-SRC-011/014).

    ``stripped_key(query_term(human_name))`` — the store title trimmed to its
    series-shaped term (the same trim the proposal ranker uses) and then run
    through the ranker's boilerplate-STRIPPED fold, which bottoms out in the ONE
    shared title fold (FRG-IMP-005). The strip is what makes the collapse real:
    store fronts name the edition slices of ONE title with per-ordinal idioms
    ("TITLE Vol. 243", "Title Issues #8", "Title #211"), each of which keeps its
    ordinal through the plain fold, so a long single-title run would otherwise
    splinter into as many groups as it has ordinals. The empty string is the
    "ungroupable" signal and never collapses with anything. The one shared fold
    is used by both the read surface (grouping) and the write surface (the
    FRG-SRC-014 sibling sweep) so the two can never diverge.
    """
    return stripped_key(query_term(human_name))


def _contains_run(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    """Whether ``needle`` occurs as a contiguous token run inside ``haystack``."""
    n = len(needle)
    if n == 0 or n > len(haystack):
        return False
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def title_confidence(term: str, name: str | None) -> float:
    """The FRG-SRC-010 confidence of one candidate name against the query term.

    ``name_similarity`` (the ONE shared SequenceMatcher-over-``matching_key``
    primitive, FRG-META-015) applied to the STRIPPED titles, lifted by the
    containment guard when the candidate's stripped title occurs whole inside
    the stripped query. This single value is what the floor, the ranking, the
    stored ``confidence`` and :data:`AUTO_MATCH_THRESHOLD` all read — the trade
    re-rank is the only thing that ever reorders around it, and it never
    changes it.
    """
    query = stripped_tokens(term)
    candidate = stripped_tokens(name)
    if not query or not candidate:
        return 0.0
    ratio = name_similarity(" ".join(query), " ".join(candidate))
    if _contains_run(query, candidate):
        # Coverage of the shorter (contained) side is 1.0 by construction; the
        # cap is what keeps a rescue proposable-but-reviewable.
        return max(ratio, MAX_CONTAINMENT_CONFIDENCE)
    return ratio


def shares_token(term: str, name: str | None) -> bool:
    """The token-overlap gate (FRG-SRC-010).

    ``True`` when the STRIPPED query term and the STRIPPED candidate name share
    at least one substantive token. A candidate that fails this is never
    proposed at any character-level similarity — the "Distant Amber Signal for
    Nobody is Guarding the Lighthouse" class (0.3673, zero shared tokens) is
    unreachable, and so is the boilerplate-only overlap of "Vane Vol. 1" vs
    "Argent Vol. 1" (which shared ``vol`` and ``1`` before the strip).
    """
    return bool(frozenset(stripped_tokens(term)) & frozenset(stripped_tokens(name)))


def trade_shape(human_name: str) -> str | None:
    """Whether a store title is TRADE-SHAPED (FRG-SRC-010, amended).

    Two shapes count, and the widening is the point: an explicit
    collected-edition cue (``detect_series_booktype`` over the shared
    ``BOOKTYPE_CUES``), OR a bare volume/book-ordinal shape. Real store titles
    for collected editions overwhelmingly carry only the second — "Vane Vol. 1",
    "Glasswing Book One" and "Ashclaw Omnibus Vol. 1" all detected as ``None``
    under cue-only detection, so the trade re-rank never fired on the purchases
    it exists for.

    Returns the detected book-type string for a cue, the sentinel
    :data:`TRADE_SHAPE_VOLUME_ORDINAL` for a bare ordinal shape, else ``None``.
    Only truthiness is consumed (the re-rank has no per-book-type behavior).
    """
    cue = detect_series_booktype(human_name)
    if cue is not None:
        return cue
    if _collected_shaped(human_name):
        return TRADE_SHAPE_VOLUME_ORDINAL
    if _VOLUME_SHAPE.search(human_name):
        return TRADE_SHAPE_VOLUME_ORDINAL
    return None


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    """One ranked match candidate.

    ``kind`` is the ACTION shape, not the provenance of the candidate: every
    candidate in ComicVine-universe mode comes from the catalog, and the ones
    already present as a library series are stamped ``"library"`` (accept =
    match to ``series_id``) while the rest stay ``"comicvine"`` (accept = add
    the volume, then match). A ``"library"`` candidate therefore carries BOTH
    ``series_id`` and — when known — ``cv_volume_id``.
    """

    kind: str  # "library" | "comicvine"
    series_id: int | None  # set for a library candidate
    cv_volume_id: int | None  # the ComicVine volume, when known
    title: str | None
    year: int | None
    confidence: float

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "series_id": self.series_id,
            "cv_volume_id": self.cv_volume_id,
            "title": self.title,
            "year": self.year,
            "confidence": round(self.confidence, 4),
        }


@dataclass(frozen=True, slots=True)
class ProposedMatch:
    """A computed proposal for one entitlement (serialized to the row).

    Two shapes, one type:

    * a **normal proposal** — ``best`` is the winning candidate, ``verdict`` is
      ``None``, and :meth:`to_json` emits exactly the historical keys;
    * a **no-plausible-match marker** — ``best`` is ``None``, ``candidates`` is
      empty and ``verdict`` is :data:`VERDICT_NO_PLAUSIBLE_MATCH`. Built by
      :meth:`no_plausible_match`; its JSON is the minimal
      ``{verdict, universe, candidates: [], auto: false}`` object, deliberately
      carrying no ``kind``/``series_id``/``cv_volume_id`` so every existing
      reader (the accept router, the FRG-SRC-008 sibling sweep, the API
      resource) treats it as "nothing to act on" without a special case.
    """

    best: MatchCandidate | None
    candidates: tuple[MatchCandidate, ...] = ()
    #: Which catalog produced the ranking — :data:`UNIVERSE_COMICVINE` or
    #: :data:`UNIVERSE_LIBRARY_FALLBACK` (no ComicVine key configured). Additive
    #: field: older readers of the stored JSON simply ignore it.
    universe: str = UNIVERSE_COMICVINE
    #: ``None`` for a real proposal; :data:`VERDICT_NO_PLAUSIBLE_MATCH` for the
    #: explicit "computation ran, nothing plausible" marker.
    verdict: str | None = None

    @classmethod
    def no_plausible_match(cls, universe: str) -> "ProposedMatch":
        """The explicit "computed, nothing plausible" verdict (FRG-SRC-010)."""
        return cls(
            best=None,
            candidates=(),
            universe=universe,
            verdict=VERDICT_NO_PLAUSIBLE_MATCH,
        )

    @property
    def is_no_match(self) -> bool:
        return self.best is None

    @property
    def proposed_series_id(self) -> int | None:
        """The library series id to store on the row (only for a library best)."""
        if self.best is None:
            return None
        return self.best.series_id if self.best.kind == "library" else None

    @property
    def confidence(self) -> float:
        return 0.0 if self.best is None else self.best.confidence

    @property
    def is_auto(self) -> bool:
        return self.best is not None and self.best.confidence >= AUTO_MATCH_THRESHOLD

    def to_json(self) -> str:
        if self.best is None:
            return json.dumps(
                {
                    "verdict": self.verdict or VERDICT_NO_PLAUSIBLE_MATCH,
                    "universe": self.universe,
                    "candidates": [],
                    "auto": False,
                },
                sort_keys=True,
            )
        return json.dumps(
            {
                "kind": self.best.kind,
                "series_id": self.best.series_id,
                "cv_volume_id": self.best.cv_volume_id,
                "title": self.best.title,
                "year": self.best.year,
                "confidence": round(self.best.confidence, 4),
                "auto": self.is_auto,
                "universe": self.universe,
                "candidates": [c.as_dict() for c in self.candidates],
            },
            sort_keys=True,
        )


@dataclass(frozen=True, slots=True)
class LibrarySeriesLite:
    """The minimal library-series shape the ranker needs.

    ``cv_volume_id`` is what makes this list the *overlay index* (every library
    series has one — ``SeriesRow.cv_volume_id`` is NOT NULL); it defaults to
    ``None`` only so the no-key library-fallback path, which ranks on titles
    alone, can be exercised without it.
    """

    id: int
    title: str | None
    start_year: int | None
    cv_volume_id: int | None = None


def rank_library(term: str, series: list[LibrarySeriesLite]) -> list[MatchCandidate]:
    """Score library series against ``term`` by folded-title similarity.

    The no-ComicVine-key fallback pool (FRG-SRC-010). Ordering here is the plain
    similarity order; the gate, floor and trade re-rank are applied by
    :func:`_propose`.
    """
    scored = [
        MatchCandidate(
            kind="library",
            series_id=s.id,
            cv_volume_id=s.cv_volume_id,
            title=s.title,
            year=s.start_year,
            confidence=title_confidence(term, s.title),
        )
        for s in series
    ]
    scored.sort(key=lambda c: (-c.confidence, c.series_id or 0))
    return scored


async def compute_proposed_match(
    *,
    human_name: str,
    library: list[LibrarySeriesLite],
    cv_client=None,
) -> ProposedMatch | None:
    """Compute a proposed match for one entitlement.

    Returns either a real :class:`ProposedMatch`, the no-plausible-match marker
    (:meth:`ProposedMatch.no_plausible_match` — the computation ran and nothing
    survived), or ``None`` when the computation could not run at all because
    ComicVine was consulted and failed, in which case the caller leaves the row
    NULL/retryable.

    ComicVine-first (FRG-SRC-010): ``cv_client.suggest_series`` supplies the
    candidate universe and ``library`` is the overlay index keyed by
    ``cv_volume_id`` — a ranked survivor already in the library becomes a
    ``"library"``-kind MATCH proposal, the rest stay ``"comicvine"``-kind ADD
    proposals. Candidates must clear the token-overlap gate before scoring and
    :data:`PROPOSE_MIN_SIMILARITY` after it — both read the ComicVine title, so
    a locally renamed series can never be gated out of its own catalog entry; a
    trade-shaped ``human_name`` re-ranks collected-edition-shaped candidates up
    (soft, ordering only), also on the ComicVine title.

    With ``cv_client=None`` the computation degrades to library-only ranking and
    records ``universe="library-fallback"`` on the result. That fallback exists
    for the NO-KEY-CONFIGURED deployment only — never as a stand-in for a CV
    call the budget refused (see :mod:`foragerr.sources.enrich`).

    A :class:`ComicVineBudgetExhausted` raised by the client PROPAGATES (the
    caller defers the item, unchanged). Any other CV failure yields ``None`` —
    a proposal is best-effort and never fatal to sync, but an upstream blip must
    not be recorded as a verdict.
    """
    term = query_term(human_name)
    # Shape detection runs on the FULL store title, not the trimmed term: a cue
    # frequently lives in the trailing parenthetical ``query_term`` strips.
    trade_cue = trade_shape(human_name)

    if cv_client is None:
        return _propose(
            rank_library(term, library),
            term=term,
            trade_cue=trade_cue,
            universe=UNIVERSE_LIBRARY_FALLBACK,
        )

    ranked = await _rank_comicvine(term, cv_client)
    if ranked is None:  # CV consulted, CV failed — no verdict to record
        return None
    overlay = {s.cv_volume_id: s for s in library if s.cv_volume_id is not None}
    return _propose(
        ranked,
        term=term,
        trade_cue=trade_cue,
        universe=UNIVERSE_COMICVINE,
        overlay=overlay,
    )


def _overlay_series(
    candidate: MatchCandidate, overlay: dict[int, LibrarySeriesLite]
) -> LibrarySeriesLite | None:
    """The library series a candidate's ComicVine volume is tracked as, if any.

    The ``have_it`` lookup: membership is decided by ``cv_volume_id`` (unique per
    series), so no second similarity pass is involved and no local title is
    consulted.
    """
    if candidate.cv_volume_id is None:
        return None
    return overlay.get(candidate.cv_volume_id)


def _apply_overlay(
    candidate: MatchCandidate, overlay: dict[int, LibrarySeriesLite]
) -> MatchCandidate:
    """Stamp a ComicVine candidate as a library MATCH when it is already tracked.

    Applied only to candidates that have ALREADY been gated, scored and ranked:
    it changes the action shape (``kind``/``series_id``) and the display title,
    never a candidate's ``confidence``, and it neither adds nor removes a
    candidate. Running it earlier would put the operator's local series title
    into the token gate and the similarity score — see the module docstring.
    """
    series = _overlay_series(candidate, overlay)
    if series is None:
        return candidate
    return replace(
        candidate,
        kind="library",
        series_id=series.id,
        title=series.title or candidate.title,
        year=candidate.year if candidate.year is not None else series.start_year,
    )


def _rank_score(trade_cue: str | None, candidate: MatchCandidate) -> float:
    """The ORDERING score: raw confidence, trade-re-ranked (design D2).

    Only a trade-shaped entitlement triggers the re-rank; a singles-shaped one
    orders on plain similarity (a collected edition is not penalized into
    invisibility — it simply has no boost to claim).
    """
    if trade_cue is None:
        return candidate.confidence
    if _collected_shaped(candidate.title or ""):
        return candidate.confidence * TRADE_RERANK_BOOST
    return candidate.confidence / TRADE_RERANK_BOOST


def _propose(
    candidates: list[MatchCandidate],
    *,
    term: str,
    trade_cue: str | None,
    universe: str,
    overlay: dict[int, LibrarySeriesLite] | None = None,
) -> ProposedMatch:
    """Gate, floor, re-rank, overlay and package a candidate pool.

    Gate first (zero SUBSTANTIVE token overlap is discarded whatever its
    similarity), floor second (on the stripped confidence, which the
    containment guard has already lifted for a decorated-query survivor —
    :func:`title_confidence`), re-rank third — so the trade boost only ever
    reorders candidates that were already honest proposals — and the library
    overlay LAST, on the retained survivors only. Every step before the overlay
    reads the ComicVine title, so a locally renamed series cannot be gated,
    floored or demoted out of its own catalog entry.

    Returns the explicit no-plausible-match marker when nothing survives: the
    computation ran, so the row records a verdict rather than staying
    indistinguishable from a deferred one.
    """
    overlay = overlay or {}
    eligible = [
        c
        for c in candidates
        if c.confidence >= PROPOSE_MIN_SIMILARITY and shares_token(term, c.title)
    ]
    if not eligible:
        return ProposedMatch.no_plausible_match(universe)

    def _tracked_series_id(c: MatchCandidate) -> int | None:
        if c.kind == "library":  # the library-fallback pool is tracked by build
            return c.series_id
        series = _overlay_series(c, overlay)
        return series.id if series is not None else None

    eligible.sort(
        key=lambda c: (
            -_rank_score(trade_cue, c),
            # A tie breaks to an already-tracked series (a match beats an add of
            # an equally-scored volume), then to a stable id order. Membership is
            # read from the overlay index, since the candidates are not stamped
            # ``kind="library"`` until after this sort.
            0 if _tracked_series_id(c) is not None else 1,
            _tracked_series_id(c) or 0,
            c.cv_volume_id or 0,
        )
    )
    ranked = tuple(_apply_overlay(c, overlay) for c in eligible[:MAX_CANDIDATES])
    return ProposedMatch(best=ranked[0], candidates=ranked, universe=universe)


async def _rank_comicvine(term: str, cv_client) -> list[MatchCandidate] | None:
    """Score ComicVine suggest candidates against ``term``.

    Propagates :class:`ComicVineBudgetExhausted` (the caller's clean defer);
    returns ``None`` on any other CV error — CV was consulted and could not
    answer, which is not the same as "CV answered with nothing" and must not be
    frozen as a verdict. An empty list means CV answered with no candidates."""
    from foragerr.metadata.errors import ComicVineBudgetExhausted, ComicVineError

    try:
        result = await cv_client.suggest_series(term)
    except ComicVineBudgetExhausted:
        raise
    except ComicVineError:
        return None
    except Exception:  # noqa: BLE001 — a proposal must never crash the sync
        return None
    scored = [
        MatchCandidate(
            kind="comicvine",
            series_id=None,
            cv_volume_id=rec.cv_volume_id,
            title=rec.name,
            year=rec.start_year,
            confidence=title_confidence(term, rec.name),
        )
        for rec in result.candidates
    ]
    scored.sort(key=lambda c: (-c.confidence, c.cv_volume_id or 0))
    return scored


__all__ = [
    "AUTO_MATCH_THRESHOLD",
    "MAX_CANDIDATES",
    "MAX_CONTAINMENT_CONFIDENCE",
    "PROPOSE_MIN_SIMILARITY",
    "STRIP_DESIGNATORS",
    "STRIP_ORDINAL_WORDS",
    "TRADE_RERANK_BOOST",
    "TRADE_SHAPE_VOLUME_ORDINAL",
    "VOLUME_SHAPE_DESIGNATORS",
    "UNIVERSE_COMICVINE",
    "UNIVERSE_LIBRARY_FALLBACK",
    "VERDICT_NO_PLAUSIBLE_MATCH",
    "LibrarySeriesLite",
    "MatchCandidate",
    "ProposedMatch",
    "compute_proposed_match",
    "group_key",
    "query_term",
    "rank_library",
    "shares_token",
    "stripped_key",
    "stripped_tokens",
    "title_confidence",
    "trade_shape",
]
