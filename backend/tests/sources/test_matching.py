"""ComicVine-first proposed-match computation (FRG-SRC-010): the token-overlap
gate, the library overlay, the trade re-rank, the no-key fallback, the
confidence floor, and unchanged budget-deferral semantics.

Historical note: these tests previously pinned the LIBRARY-FIRST two-pool
mechanism (a confident library hit short-circuited before any CV call). That
mechanism is what FRG-SRC-010 replaces — the library is now an overlay on the
ComicVine universe — so the tests that asserted it have been rewritten rather
than kept. Everything they were really protecting (a tracked series proposes a
MATCH, a trade never auto-files into the singles run, budget exhaustion defers
cleanly) is re-asserted below against the new mechanism.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from foragerr.metadata.errors import ComicVineBudgetExhausted, ComicVineError
from foragerr.sources.matching import (
    AUTO_MATCH_THRESHOLD,
    PROPOSE_MIN_SIMILARITY,
    UNIVERSE_COMICVINE,
    UNIVERSE_LIBRARY_FALLBACK,
    VERDICT_NO_PLAUSIBLE_MATCH,
    LibrarySeriesLite,
    compute_proposed_match,
    query_term,
    shares_token,
)


def _assert_no_plausible_match(proposal, *, universe) -> dict:
    """The explicit verdict shape: computed, nothing plausible (FRG-SRC-010).

    Distinguishable from a NULL (never-computed / deferred) proposal, and inert
    for every existing reader — no ``kind``, no ids, no candidates, never auto.
    """
    assert proposal is not None, "a ran-and-found-nothing computation is a verdict"
    assert proposal.is_no_match is True
    assert proposal.best is None
    assert proposal.candidates == ()
    assert proposal.verdict == VERDICT_NO_PLAUSIBLE_MATCH
    assert proposal.universe == universe
    assert proposal.proposed_series_id is None
    assert proposal.is_auto is False
    payload = json.loads(proposal.to_json())
    assert payload == {
        "verdict": "no-plausible-match",
        "universe": universe,
        "candidates": [],
        "auto": False,
    }
    return payload


def _lib(*rows) -> list[LibrarySeriesLite]:
    """Library overlay index rows: ``(id, title, year, cv_volume_id)``."""
    return [
        LibrarySeriesLite(id=i, title=t, start_year=y, cv_volume_id=cv)
        for i, t, y, cv in rows
    ]


class _FakeCV:
    """A ComicVine client stub exposing only ``suggest_series`` (what the ranker
    reads); candidates are namespaces with the three fields it uses."""

    def __init__(self, candidates=None, *, raises=None):
        self._candidates = candidates or []
        self._raises = raises
        self.calls = 0
        self.terms: list[str] = []

    async def suggest_series(self, term):
        self.calls += 1
        self.terms.append(term)
        if self._raises is not None:
            raise self._raises
        return SimpleNamespace(candidates=self._candidates)


def _cand(cvid, name, year=None):
    return SimpleNamespace(cv_volume_id=cvid, name=name, start_year=year)


# --- query term + gate primitives -------------------------------------------


@pytest.mark.req("FRG-SRC-010")
def test_query_term_strips_issue_and_parenthetical():
    assert query_term("Synthetic Hero #1") == "Synthetic Hero"
    assert (
        query_term("Synthetic Hero Vol. 1 (collects #1-6)") == "Synthetic Hero Vol. 1"
    )


@pytest.mark.req("FRG-SRC-010")
def test_token_gate_uses_the_shared_fold_and_ignores_articles():
    # "the" is dropped by matching_key on both sides, so it is never the token
    # that lets an unrelated candidate through.
    assert shares_token("Something is Killing the Children", "The Children of Doom")
    assert not shares_token("Something is Killing the Children", "The Green Arrow")
    assert not shares_token("Anything", None)


# --- the gate: the live-rig repro pair --------------------------------------


@pytest.mark.req("FRG-SRC-010")
async def test_zero_token_overlap_is_never_proposed_the_green_arrow_repro():
    """The exact live-rig repro (finding #7): "Absolute Green Arrow" scored
    0.3273 against "Something is Killing the Children Vol. 8" on a
    character-level ratio. Zero shared tokens ⇒ it is discarded BEFORE scoring,
    at any similarity, and the row carries the explicit no-match verdict."""
    cv = _FakeCV(candidates=[_cand(1, "Absolute Green Arrow", 2024)])
    proposal = await compute_proposed_match(
        human_name="Something is Killing the Children Vol. 8",
        library=_lib((7, "Absolute Green Arrow", 2024, 1)),  # even if tracked
        cv_client=cv,
    )
    assert cv.calls == 1
    _assert_no_plausible_match(proposal, universe=UNIVERSE_COMICVINE)


@pytest.mark.req("FRG-SRC-010")
async def test_zero_overlap_gate_also_applies_to_the_library_fallback():
    proposal = await compute_proposed_match(
        human_name="Something is Killing the Children Vol. 8",
        library=_lib((7, "Absolute Green Arrow", 2024, 1)),
        cv_client=None,
    )
    _assert_no_plausible_match(proposal, universe=UNIVERSE_LIBRARY_FALLBACK)


# --- the library overlay ----------------------------------------------------


@pytest.mark.req("FRG-SRC-010")
async def test_in_library_comicvine_candidate_proposes_a_match():
    """A CV candidate already present as a library series is stamped
    ``kind="library"`` with its ``series_id`` — accepting MATCHES in one
    action instead of adding a duplicate."""
    cv = _FakeCV(candidates=[_cand(556, "Synthetic Hero", 2018)])
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero #1",
        library=_lib((7, "Synthetic Hero", 2018, 556)),
        cv_client=cv,
    )
    assert cv.calls == 1  # CV is the universe: it is always consulted
    assert proposal is not None
    assert proposal.best.kind == "library"
    assert proposal.best.series_id == 7
    assert proposal.best.cv_volume_id == 556  # the overlay keeps the CV identity
    assert proposal.proposed_series_id == 7
    assert proposal.universe == UNIVERSE_COMICVINE
    assert proposal.confidence >= AUTO_MATCH_THRESHOLD
    assert proposal.is_auto is True
    assert '"kind": "library"' in proposal.to_json()


@pytest.mark.req("FRG-SRC-010")
async def test_not_in_library_candidate_proposes_an_add():
    cv = _FakeCV(candidates=[_cand(4242, "Synthetic Hero", 2018)])
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero #1",
        library=_lib((1, "A Completely Unrelated Comic", 2001, 99)),
        cv_client=cv,
    )
    assert cv.calls == 1
    assert proposal is not None
    assert proposal.best.kind == "comicvine"
    assert proposal.best.cv_volume_id == 4242
    assert proposal.best.series_id is None
    assert proposal.proposed_series_id is None  # nothing local yet
    assert proposal.universe == UNIVERSE_COMICVINE


@pytest.mark.req("FRG-SRC-010")
async def test_overlay_wins_a_tie_against_an_equally_scored_add():
    """Same title, same score: the already-tracked volume proposes the match."""
    cv = _FakeCV(
        candidates=[
            _cand(4242, "Synthetic Hero", 2018),
            _cand(556, "Synthetic Hero", 2018),
        ]
    )
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero #1",
        library=_lib((7, "Synthetic Hero", 2018, 556)),
        cv_client=cv,
    )
    assert proposal is not None
    assert proposal.best.kind == "library"
    assert proposal.best.series_id == 7
    # Both remain offered — the overlay reorders, it never drops a candidate.
    assert {c.cv_volume_id for c in proposal.candidates} == {4242, 556}


@pytest.mark.req("FRG-SRC-010")
async def test_overlay_is_applied_after_gating_so_a_local_rename_cannot_demote():
    """The operator's local series title is a DISPLAY name, not evidence about
    catalog identity: a library series titled ``"Saga (2012)"`` for ComicVine's
    ``"Saga"`` must still be scored on the CV title.

    Applying the overlay before the gate scored the store title against the
    LOCAL title instead — 0.6154 here rather than 1.0 — silently dropping the
    row below the auto-match threshold and leaking shelf metadata into the
    CV-first gate."""
    cv = _FakeCV(candidates=[_cand(18975, "Saga", 2012)])
    proposal = await compute_proposed_match(
        human_name="Saga #1",
        library=_lib((7, "Saga (2012)", 2012, 18975)),
        cv_client=cv,
    )
    assert proposal is not None
    # Scored on the CV title...
    assert proposal.confidence == pytest.approx(1.0)
    assert proposal.confidence >= AUTO_MATCH_THRESHOLD
    # ...and the overlay still lands: kind, series_id and the DISPLAY title.
    assert proposal.best.kind == "library"
    assert proposal.best.series_id == 7
    assert proposal.best.cv_volume_id == 18975
    assert proposal.best.title == "Saga (2012)"


@pytest.mark.req("FRG-SRC-010")
async def test_local_title_sharing_no_token_with_the_query_still_matches():
    """The extreme of the same bug: a library series renamed to something that
    shares NO token with the store title (a localized/alternate title) used to
    be discarded by the token gate — even though the ComicVine candidate it
    overlays matched the query exactly."""
    cv = _FakeCV(candidates=[_cand(18975, "Saga", 2012)])
    proposal = await compute_proposed_match(
        human_name="Saga #1",
        library=_lib((7, "Kroniki Wygnancow", 2012, 18975)),
        cv_client=cv,
    )
    # The CV title cleared the gate; the overlay is display-only.
    assert proposal is not None
    assert proposal.best.kind == "library"
    assert proposal.best.series_id == 7


@pytest.mark.req("FRG-SRC-010")
async def test_local_rename_cannot_win_the_gate_for_an_unrelated_volume():
    """The converse guard: the overlay must not RESCUE a candidate either. A
    tracked volume whose CV title fails the gate stays discarded however
    conveniently its local title matches the store title."""
    cv = _FakeCV(candidates=[_cand(1, "Absolute Green Arrow", 2024)])
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero #1",
        # The local title matches the store title; the CV title does not.
        library=_lib((7, "Synthetic Hero", 2018, 1)),
        cv_client=cv,
    )
    _assert_no_plausible_match(proposal, universe=UNIVERSE_COMICVINE)


# --- the trade re-rank ------------------------------------------------------


@pytest.mark.req("FRG-SRC-010")
async def test_trade_shaped_title_prefers_the_collected_edition():
    """Raw similarity favours the singles line (0.9091 vs 0.8571); the shared
    collected-edition cue vocabulary flips the order. The singles line is still
    listed — a re-rank, never a filter."""
    cv = _FakeCV(
        candidates=[
            _cand(11, "Synthetic Hero Vol 1", 2018),  # singles line
            _cand(22, "Synthetic Hero TPB", 2020),  # collected edition
        ]
    )
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero Vol 1 TPB",
        library=[],
        cv_client=cv,
    )
    assert proposal is not None
    assert proposal.best.cv_volume_id == 22
    assert [c.cv_volume_id for c in proposal.candidates] == [22, 11]
    # The re-rank is ordering-only: the reported confidence stays the raw
    # similarity, so the boost can never lift a candidate over the auto bar.
    assert proposal.best.confidence == pytest.approx(0.8571, abs=1e-4)


@pytest.mark.req("FRG-SRC-010")
async def test_singles_shaped_title_keeps_plain_similarity_order():
    """The control for the test above: with no cue in the store title the same
    two candidates rank on similarity alone."""
    cv = _FakeCV(
        candidates=[
            _cand(11, "Synthetic Hero Vol 1", 2018),
            _cand(22, "Synthetic Hero TPB", 2020),
        ]
    )
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero Vol 1",
        library=[],
        cv_client=cv,
    )
    assert proposal is not None
    assert proposal.best.cv_volume_id == 11


@pytest.mark.req("FRG-SRC-010")
async def test_collected_edition_scores_below_auto_threshold():
    """A trade's long title must not silently auto-file into the singles run."""
    cv = _FakeCV(candidates=[_cand(556, "Synthetic Hero", 2018)])
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero: The Collected Edition Vol. 1 (collects #1-6)",
        library=_lib((7, "Synthetic Hero", 2018, 556)),
        cv_client=cv,
    )
    assert proposal is not None
    assert proposal.confidence < AUTO_MATCH_THRESHOLD
    assert proposal.is_auto is False


# --- the floor --------------------------------------------------------------


@pytest.mark.req("FRG-SRC-010")
async def test_gated_candidate_below_the_floor_is_not_proposed():
    """A shared token is necessary, not sufficient: a survivor still has to
    clear PROPOSE_MIN_SIMILARITY."""
    cv = _FakeCV(
        candidates=[_cand(9, "Hero of the Nine Realms Omnibus Companion", 1999)]
    )
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero #1", library=[], cv_client=cv
    )
    _assert_no_plausible_match(proposal, universe=UNIVERSE_COMICVINE)


@pytest.mark.req("FRG-SRC-010")
async def test_floor_survivor_is_proposed_and_the_weak_sibling_is_dropped():
    cv = _FakeCV(
        candidates=[
            _cand(9, "Hero of the Nine Realms Omnibus Companion", 1999),
            _cand(10, "Synthetic Hero", 2018),
        ]
    )
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero #1", library=[], cv_client=cv
    )
    assert proposal is not None
    assert proposal.best.cv_volume_id == 10
    assert all(c.confidence >= PROPOSE_MIN_SIMILARITY for c in proposal.candidates)
    assert 9 not in {c.cv_volume_id for c in proposal.candidates}


# --- the no-key fallback ----------------------------------------------------


@pytest.mark.req("FRG-SRC-010")
async def test_no_key_falls_back_to_library_and_says_so():
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero #1",
        library=_lib((7, "Synthetic Hero", 2018, 556)),
        cv_client=None,
    )
    assert proposal is not None
    assert proposal.universe == UNIVERSE_LIBRARY_FALLBACK
    assert proposal.best.kind == "library"
    assert proposal.best.series_id == 7
    assert '"universe": "library-fallback"' in proposal.to_json()


@pytest.mark.req("FRG-SRC-010")
async def test_comicvine_universe_is_marked_on_the_proposal():
    cv = _FakeCV(candidates=[_cand(4242, "Synthetic Hero", 2018)])
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero #1", library=[], cv_client=cv
    )
    assert proposal is not None
    assert proposal.universe == UNIVERSE_COMICVINE
    assert '"universe": "comicvine"' in proposal.to_json()


# --- budget + failure semantics (unchanged) ---------------------------------


@pytest.mark.req("FRG-SRC-010")
async def test_budget_exhausted_propagates_for_clean_defer():
    cv = _FakeCV(raises=ComicVineBudgetExhausted("volume", retry_after_seconds=60))
    with pytest.raises(ComicVineBudgetExhausted):
        await compute_proposed_match(
            human_name="Nothing Local Here #3",
            library=_lib((1, "Unrelated", 2000, 5)),
            cv_client=cv,
        )


@pytest.mark.req("FRG-SRC-010")
async def test_budget_exhausted_propagates_even_with_a_perfect_library_row():
    """The library is an overlay, not a short-circuit: a tracked series does not
    swallow the deferral signal the caller relies on."""
    cv = _FakeCV(raises=ComicVineBudgetExhausted("volume", retry_after_seconds=60))
    with pytest.raises(ComicVineBudgetExhausted):
        await compute_proposed_match(
            human_name="Synthetic Hero #1",
            library=_lib((7, "Synthetic Hero", 2018, 556)),
            cv_client=cv,
        )


@pytest.mark.req("FRG-SRC-010")
async def test_other_comicvine_errors_are_not_fatal():
    """A CV failure is not a verdict: ``None`` (row stays NULL/retryable), NOT
    the no-plausible-match marker — freezing a marker on an upstream blip is the
    same hazard as freezing a fallback proposal on a budget hit."""
    cv = _FakeCV(raises=ComicVineError("upstream 500"))
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero #1",
        library=_lib((7, "Synthetic Hero", 2018, 556)),
        cv_client=cv,
    )
    assert proposal is None  # no catalog verdict is available, so none is faked


@pytest.mark.req("FRG-SRC-010")
async def test_empty_library_fallback_pool_is_an_explicit_no_match_verdict():
    """The no-key fallback RAN (it just had nothing to rank), so it records the
    verdict rather than leaving the row indistinguishable from a deferred one."""
    proposal = await compute_proposed_match(
        human_name="Wholly Unknown Comic #1", library=[], cv_client=None
    )
    _assert_no_plausible_match(proposal, universe=UNIVERSE_LIBRARY_FALLBACK)


@pytest.mark.req("FRG-SRC-010")
async def test_comicvine_answering_with_no_candidates_is_a_no_match_verdict():
    cv = _FakeCV(candidates=[])
    proposal = await compute_proposed_match(
        human_name="Wholly Unknown Comic #1", library=[], cv_client=cv
    )
    assert cv.calls == 1
    _assert_no_plausible_match(proposal, universe=UNIVERSE_COMICVINE)


@pytest.mark.req("FRG-SRC-010")
async def test_normal_proposal_json_carries_no_verdict_key():
    """The marker is ADDITIVE: a real proposal's serialized shape is unchanged,
    so every existing reader of the stored JSON is untouched."""
    cv = _FakeCV(candidates=[_cand(4242, "Synthetic Hero", 2018)])
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero #1", library=[], cv_client=cv
    )
    payload = json.loads(proposal.to_json())
    assert proposal.verdict is None
    assert set(payload) == {
        "kind",
        "series_id",
        "cv_volume_id",
        "title",
        "year",
        "confidence",
        "auto",
        "universe",
        "candidates",
    }
