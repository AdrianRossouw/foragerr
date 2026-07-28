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
gated and scored, each one whose ``cv_volume_id`` is already present as a
library series is re-stamped ``kind="library"`` with that ``series_id``, so
accepting it MATCHES in one action; a candidate not in the library stays
``kind="comicvine"`` and accepting it ADDS-and-matches in one action (the
FRG-SRC-008 seam handles both). This is the inversion of the old library-first
two-pool strategy, whose small-library ranking is what let "Absolute Green
Arrow" propose itself for "Something is Killing the Children Vol. 8".

**Token-overlap gate.** A candidate is discarded BEFORE similarity ranking
unless its folded title shares at least one token with the folded query term
(articles are already dropped by the fold). Character-level similarity alone is
not evidence of identity — the repro pair above scores 0.3273 with zero shared
tokens — so the gate, not the floor, is what makes that class impossible.
:data:`PROPOSE_MIN_SIMILARITY` then applies to the gated survivors.

**Trade re-rank (soft).** When the store title itself carries a
collected-edition cue, candidates carrying a collected cue are boosted and bare
ones demoted, so a trade-shaped purchase proposes the collected-edition volume
rather than the singles line. ComicVine carries no book-type field, so name cues
are the only signal available and the re-rank must stay soft: it reorders, it
never excludes, and it never alters a candidate's reported ``confidence``. The
import-time trade guard (FRG-PP-022 guard 1) remains the backstop.

**No-key fallback.** With no ``cv_client`` (no ComicVine key configured) the
computation degrades to library-only ranking — same gate, same floor — and says
so: the proposal carries ``universe="library-fallback"`` instead of
``"comicvine"``, so the UI never presents a shelf-local guess as a catalog
verdict.

**No plausible match.** When nothing survives gate + floor the function returns
``None`` and the row keeps a NULL proposal. That is a verdict about the
*automatic* computation only, never a terminal state: the per-row ComicVine
search (FRG-UI-039) is present on every reviewable row.

**Budget-aware (FRG-META-016).** A :class:`ComicVineBudgetExhausted` mid-batch
is never swallowed into a bad proposal: it propagates so the caller leaves the
entitlement ``new`` with a NULL proposal — a later sync retries. Deferral
semantics are unchanged from the library-first implementation. CV is consulted
at most once per new comic entitlement.

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

from foragerr.library.booktype import detect_series_booktype
from foragerr.metadata.search import name_similarity
from foragerr.parser.normalize import matching_key

#: Confidence at/above which the opt-in auto-sync path may auto-accept (0..1).
AUTO_MATCH_THRESHOLD = 0.85

#: Floor below which no proposal is stored at all (a guess this weak is noise);
#: the entitlement stays ``new`` with a NULL proposal, surfaced as unmatched.
#: Applied to the gated survivors, on the RAW similarity (never the re-ranked
#: score) so the trade boost cannot smuggle a weak candidate over the floor.
PROPOSE_MIN_SIMILARITY = 0.5

#: How many ranked candidates to retain in the stored proposal for the UI.
MAX_CANDIDATES = 3

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

_TRAILING_ISSUE = re.compile(r"\s*#\s*[0-9]+[a-z.]*\s*$", re.IGNORECASE)
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*$")


def query_term(human_name: str) -> str:
    """The store title reduced to a series-shaped query term.

    Drops a trailing issue token (``"Hero #1"`` → ``"Hero"``) and a trailing
    parenthetical (``"... (collects #1-6)"``) so the folded-title similarity
    keys off the series name, not the copy-specific suffix. Folding itself is
    ``name_similarity``'s job (``matching_key``) — this only trims obvious
    per-copy noise."""
    term = _PARENTHETICAL.sub("", human_name).strip()
    term = _TRAILING_ISSUE.sub("", term).strip()
    return term or human_name.strip()


def _fold_tokens(text: str | None) -> frozenset[str]:
    """The folded token set of a title, via the ONE shared fold."""
    if not text:
        return frozenset()
    key = matching_key(text)
    return frozenset(key.split()) if key else frozenset()


def shares_token(term: str, name: str | None) -> bool:
    """The token-overlap gate (FRG-SRC-010).

    ``True`` when the folded query term and the folded candidate name share at
    least one token. A candidate that fails this is never proposed at any
    character-level similarity — the "Absolute Green Arrow for Something is
    Killing the Children" class (0.3273, zero shared tokens) is unreachable.
    """
    return bool(_fold_tokens(term) & _fold_tokens(name))


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
    """A computed proposal for one entitlement (serialized to the row)."""

    best: MatchCandidate
    candidates: tuple[MatchCandidate, ...]
    #: Which catalog produced the ranking — :data:`UNIVERSE_COMICVINE` or
    #: :data:`UNIVERSE_LIBRARY_FALLBACK` (no ComicVine key configured). Additive
    #: field: older readers of the stored JSON simply ignore it.
    universe: str = UNIVERSE_COMICVINE

    @property
    def proposed_series_id(self) -> int | None:
        """The library series id to store on the row (only for a library best)."""
        return self.best.series_id if self.best.kind == "library" else None

    @property
    def confidence(self) -> float:
        return self.best.confidence

    @property
    def is_auto(self) -> bool:
        return self.best.confidence >= AUTO_MATCH_THRESHOLD

    def to_json(self) -> str:
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
            confidence=name_similarity(term, s.title),
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
    """Compute a proposed match for one entitlement, or ``None`` (leave NULL).

    ComicVine-first (FRG-SRC-010): ``cv_client.suggest_series`` supplies the
    candidate universe and ``library`` is the overlay index keyed by
    ``cv_volume_id`` — a candidate already in the library becomes a
    ``"library"``-kind MATCH proposal, the rest stay ``"comicvine"``-kind ADD
    proposals. Candidates must clear the token-overlap gate before scoring and
    :data:`PROPOSE_MIN_SIMILARITY` after it; a trade-shaped ``human_name``
    re-ranks collected-edition-shaped candidates up (soft, ordering only).

    With ``cv_client=None`` the computation degrades to library-only ranking and
    records ``universe="library-fallback"`` on the result.

    A :class:`ComicVineBudgetExhausted` raised by the client PROPAGATES (the
    caller defers the item, unchanged). Any other CV failure is swallowed to an
    empty candidate list — a proposal is best-effort, never fatal to sync.
    """
    term = query_term(human_name)
    # Cue detection runs on the FULL store title, not the trimmed term: a cue
    # frequently lives in the trailing parenthetical ``query_term`` strips.
    trade_cue = detect_series_booktype(human_name)

    if cv_client is None:
        return _propose(
            rank_library(term, library),
            term=term,
            trade_cue=trade_cue,
            universe=UNIVERSE_LIBRARY_FALLBACK,
        )

    overlay = {s.cv_volume_id: s for s in library if s.cv_volume_id is not None}
    candidates = [
        _apply_overlay(c, overlay) for c in await _rank_comicvine(term, cv_client)
    ]
    return _propose(
        candidates, term=term, trade_cue=trade_cue, universe=UNIVERSE_COMICVINE
    )


def _apply_overlay(
    candidate: MatchCandidate, overlay: dict[int, LibrarySeriesLite]
) -> MatchCandidate:
    """Stamp a ComicVine candidate as a library MATCH when it is already tracked.

    The ``have_it`` pattern: membership is decided by ``cv_volume_id`` (unique
    per series), so no second similarity pass is involved and no candidate is
    added or removed — only its action shape changes.
    """
    series = (
        overlay.get(candidate.cv_volume_id)
        if candidate.cv_volume_id is not None
        else None
    )
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
    if detect_series_booktype(candidate.title or "") is not None:
        return candidate.confidence * TRADE_RERANK_BOOST
    return candidate.confidence / TRADE_RERANK_BOOST


def _propose(
    candidates: list[MatchCandidate],
    *,
    term: str,
    trade_cue: str | None,
    universe: str,
) -> ProposedMatch | None:
    """Gate, floor, re-rank and package a candidate pool into a proposal.

    Gate first (zero token overlap is discarded whatever its similarity), floor
    second (on raw confidence), re-rank last — so the trade boost only ever
    reorders candidates that were already honest proposals. Returns ``None``
    when nothing survives: the "no plausible automatic match" verdict.
    """
    eligible = [
        c
        for c in candidates
        if c.confidence >= PROPOSE_MIN_SIMILARITY and shares_token(term, c.title)
    ]
    if not eligible:
        return None
    eligible.sort(
        key=lambda c: (
            -_rank_score(trade_cue, c),
            # A tie breaks to an already-tracked series (a match beats an add of
            # an equally-scored volume), then to a stable id order.
            0 if c.kind == "library" else 1,
            c.series_id or 0,
            c.cv_volume_id or 0,
        )
    )
    return ProposedMatch(
        best=eligible[0],
        candidates=tuple(eligible[:MAX_CANDIDATES]),
        universe=universe,
    )


async def _rank_comicvine(term: str, cv_client) -> list[MatchCandidate]:
    """Score ComicVine suggest candidates against ``term``.

    Propagates :class:`ComicVineBudgetExhausted` (the caller's clean defer);
    swallows any other CV error to an empty pool (a proposal is optional)."""
    from foragerr.metadata.errors import ComicVineBudgetExhausted, ComicVineError

    try:
        result = await cv_client.suggest_series(term)
    except ComicVineBudgetExhausted:
        raise
    except ComicVineError:
        return []
    except Exception:  # noqa: BLE001 — a proposal must never crash the sync
        return []
    scored = [
        MatchCandidate(
            kind="comicvine",
            series_id=None,
            cv_volume_id=rec.cv_volume_id,
            title=rec.name,
            year=rec.start_year,
            confidence=name_similarity(term, rec.name),
        )
        for rec in result.candidates
    ]
    scored.sort(key=lambda c: (-c.confidence, c.cv_volume_id or 0))
    return scored


__all__ = [
    "AUTO_MATCH_THRESHOLD",
    "MAX_CANDIDATES",
    "PROPOSE_MIN_SIMILARITY",
    "TRADE_RERANK_BOOST",
    "UNIVERSE_COMICVINE",
    "UNIVERSE_LIBRARY_FALLBACK",
    "LibrarySeriesLite",
    "MatchCandidate",
    "ProposedMatch",
    "compute_proposed_match",
    "query_term",
    "rank_library",
    "shares_token",
]
