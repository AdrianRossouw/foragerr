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
"Absolute Green Arrow" propose itself for "Something is Killing the Children
Vol. 8".

**The overlay is applied strictly AFTER gating and ranking.** It carries a
*display* title (the operator's local series title, which may legitimately
diverge from the catalog's — ``"Saga (2012)"`` locally for CV's ``"Saga"``), and
a display title is not evidence about catalog identity. Feeding it into the
token gate or the similarity score would let a local rename discard a correct
in-library candidate, and would leak shelf-local metadata into a gate that is
supposed to be CV-first. So the gate, the floor, the similarity and the trade
re-rank all read the ComicVine title; the overlay then re-stamps
``kind``/``series_id``/title on the ranked survivors, changing the ACTION shape
and the label, never the verdict.

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

#: ``ProposedMatch.verdict`` for a computation that RAN and found nothing
#: plausible. Stored on the row so "computed, no match" is distinguishable from
#: "not computed yet" (NULL). A normal proposal carries ``verdict = None`` and
#: its serialized shape is unchanged.
VERDICT_NO_PLAUSIBLE_MATCH = "no-plausible-match"

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
    if detect_series_booktype(candidate.title or "") is not None:
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

    Gate first (zero token overlap is discarded whatever its similarity), floor
    second (on raw confidence), re-rank third — so the trade boost only ever
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
    "VERDICT_NO_PLAUSIBLE_MATCH",
    "LibrarySeriesLite",
    "MatchCandidate",
    "ProposedMatch",
    "compute_proposed_match",
    "query_term",
    "rank_library",
    "shares_token",
]
