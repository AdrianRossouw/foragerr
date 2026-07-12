"""Server-side proposed-match computation for new entitlements (FRG-SRC-004).

When a sync lands a NEW comic entitlement it carries no match. This module
computes a *proposed* match server-side so the review UI can render a suggestion
and the auto-sync path (when ON) can act on a confident one. It reuses the
existing relevance machinery rather than inventing a second ranker:

* :func:`foragerr.metadata.search.name_similarity` — the SequenceMatcher-over-
  ``matching_key`` score (FRG-META-015), the same primitive the ComicVine
  search/suggest ranking sorts by;
* :func:`foragerr.parser.normalize.matching_key` (via ``name_similarity``) — the
  single title-folding implementation (FRG-IMP-005);
* the library series list + the ComicVine suggest endpoint as the two candidate
  pools.

**Two-pool strategy.** The store title is matched *library-first*: an item the
operator already tracks should link to that series (a free, CV-budget-free
match, and the booktype/containment model FRG-SER-018/020 already lives on the
row). Only when no library series clears the propose floor is ComicVine
consulted (``suggest_series``), and its top candidate proposed as an *add*.

**Budget-aware (FRG-META-016).** A :class:`ComicVineBudgetExhausted` mid-batch
is never swallowed into a bad proposal: it propagates so the caller leaves the
entitlement ``new`` with a NULL proposal — a later sync retries. CV is consulted
at most once per new comic entitlement (and never at all when a library match
wins), so a batch of purchases cannot burn a path budget.

**Auto-match threshold** (task 3.2, decided here). ``AUTO_MATCH_THRESHOLD =
0.85``: the confidence at/above which the opt-in auto-sync path (FRG-SRC-004)
may accept-and-download without operator review. It is a ``name_similarity``
value — a normalized-title SequenceMatcher ratio in ``[0, 1]`` — chosen from the
fixtures: ``"Synthetic Hero #1"`` folds to ``synthetic hero 1`` which scores
~0.93 against a ``"Synthetic Hero"`` library series (clears the bar), while the
collected edition ``"...The Collected Edition Vol. 1 (collects #1-6)"`` folds to
a long token run that scores well under 0.85 against the same series (correctly
withheld — a trade must not silently auto-file into the singles run). 0.85 sits
in the gap: high enough that a different series (a few shared words) never
clears it, low enough that punctuation/casing/spacing noise on the true title
does. Below the bar an item still gets a *proposed* match for the UI; it just
stays in review until the operator acts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from foragerr.metadata.search import name_similarity

#: Confidence at/above which the opt-in auto-sync path may auto-accept (0..1).
AUTO_MATCH_THRESHOLD = 0.85

#: Floor below which no proposal is stored at all (a guess this weak is noise);
#: the entitlement stays ``new`` with a NULL proposal, surfaced as unmatched.
PROPOSE_MIN_SIMILARITY = 0.5

#: How many ranked candidates to retain in the stored proposal for the UI.
MAX_CANDIDATES = 3

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


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    """One ranked match candidate (library series or ComicVine volume)."""

    kind: str  # "library" | "comicvine"
    series_id: int | None  # set for a library candidate
    cv_volume_id: int | None  # set for a comicvine candidate
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
                "candidates": [c.as_dict() for c in self.candidates],
            },
            sort_keys=True,
        )


@dataclass(frozen=True, slots=True)
class LibrarySeriesLite:
    """The minimal library-series shape the ranker needs (id, title, year)."""

    id: int
    title: str | None
    start_year: int | None


def rank_library(
    term: str, series: list[LibrarySeriesLite]
) -> list[MatchCandidate]:
    """Rank library series against ``term`` by folded-title similarity."""
    scored = [
        MatchCandidate(
            kind="library",
            series_id=s.id,
            cv_volume_id=None,
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

    Library-first: if the best library candidate clears
    :data:`PROPOSE_MIN_SIMILARITY` it is proposed with no CV call. Otherwise, if
    a ``cv_client`` is supplied, ``suggest_series`` is consulted and its best
    candidate proposed as an add. A :class:`ComicVineBudgetExhausted` raised by
    the client PROPAGATES (the caller defers the item). Any other CV failure is
    swallowed to ``None`` — a proposal is best-effort, never fatal to sync.
    """
    term = query_term(human_name)

    lib_ranked = rank_library(term, library)
    best_lib = lib_ranked[0] if lib_ranked else None
    if best_lib is not None and best_lib.confidence >= PROPOSE_MIN_SIMILARITY:
        return ProposedMatch(
            best=best_lib, candidates=tuple(lib_ranked[:MAX_CANDIDATES])
        )

    if cv_client is None:
        # No CV pool and no confident library hit → surface a weak library guess
        # if we have one, else nothing.
        if best_lib is not None and best_lib.confidence > 0:
            return ProposedMatch(best=best_lib, candidates=(best_lib,))
        return None

    cv_ranked = await _rank_comicvine(term, cv_client)
    best_cv = cv_ranked[0] if cv_ranked else None

    # Choose the stronger of the two pools' best (a tie breaks to library — a
    # free, already-tracked match beats an add of an equally-scored CV volume).
    pool = [c for c in (best_lib, best_cv) if c is not None]
    if not pool:
        return None
    pool.sort(key=lambda c: (-c.confidence, 0 if c.kind == "library" else 1))
    best = pool[0]
    if best.kind == "comicvine" and best.confidence < PROPOSE_MIN_SIMILARITY:
        # A weak CV guess is noise; fall back to a (weak) library guess or NULL.
        if best_lib is not None and best_lib.confidence > 0:
            return ProposedMatch(best=best_lib, candidates=(best_lib,))
        return None
    ranked = cv_ranked if best.kind == "comicvine" else lib_ranked
    return ProposedMatch(best=best, candidates=tuple(ranked[:MAX_CANDIDATES]))


async def _rank_comicvine(term: str, cv_client) -> list[MatchCandidate]:
    """Rank ComicVine suggest candidates against ``term``.

    Propagates :class:`ComicVineBudgetExhausted`; swallows any other CV error to
    an empty ranking (a proposal is optional)."""
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
    "LibrarySeriesLite",
    "MatchCandidate",
    "ProposedMatch",
    "compute_proposed_match",
    "query_term",
    "rank_library",
]
