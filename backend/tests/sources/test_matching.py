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
    MAX_CONTAINMENT_CONFIDENCE,
    PROPOSE_MIN_SIMILARITY,
    UNIVERSE_COMICVINE,
    UNIVERSE_LIBRARY_FALLBACK,
    VERDICT_NO_PLAUSIBLE_MATCH,
    LibrarySeriesLite,
    compute_proposed_match,
    query_term,
    shares_token,
    stripped_key,
    title_confidence,
    trade_shape,
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


@pytest.mark.req("FRG-SRC-011")
def test_query_term_reapplies_the_parenthetical_strip_after_the_issue_strip():
    """The print-year form "Ember (1992) #1": the parenthetical is not TRAILING
    until the issue token is gone, so a single pass left "Ember (1992)".

    That mattered beyond similarity: ``group_key`` is
    ``matching_key(query_term(...))``, so every year-stamped row folded to its
    own key ("ember 1992") and a long single-title run's collapse group
    fragmented by print year. The trims now alternate until the term stops
    shrinking.
    """
    from foragerr.parser.normalize import matching_key

    assert query_term("Ember (1992) #1") == "Ember"
    assert query_term("Ember (1992) #274") == "Ember"
    assert query_term("Ember #5") == "Ember"
    # The group-key consequence: all three rows collapse into one group.
    keys = {
        matching_key(query_term(t))
        for t in ("Ember (1992) #1", "Ember (1992) #274", "Ember #5")
    }
    assert keys == {"ember"}


# --- strip-then-score primitives --------------------------------------------


@pytest.mark.req("FRG-SRC-010")
def test_stripped_key_removes_edition_boilerplate_only():
    """Designators, bare ordinals and the shared collected-edition cues go; the
    substantive title words stay."""
    assert stripped_key("Vane Volume 1") == "vane"
    assert stripped_key("Vane Vol. 3") == "vane"
    assert stripped_key("Glasswing Book One") == "glasswing"
    assert stripped_key("Synthetic Hero TPB") == "synthetic hero"
    assert stripped_key("Rook Hardcover") == "rook"
    assert stripped_key("Ashclaw Omnibus Volume 1: Fang of Devastation") == (
        "ashclaw fang of devastation"
    )
    # Nothing substantive is lost from a plain title.
    assert stripped_key("Nobody is Guarding the Lighthouse") == (
        "nobody is guarding lighthouse"
    )


@pytest.mark.req("FRG-SRC-010")
def test_an_all_boilerplate_title_keeps_its_tokens_rather_than_vanishing():
    """"Volume 1" strips to nothing; it keeps its folded tokens instead, the
    same guard ``matching_key`` applies to an articles-only title. An empty
    token set would gate-match nothing at all (or, symmetrically, everything)."""
    assert stripped_key("Volume 1") == "volume 1"
    assert stripped_key("52") == "52"


@pytest.mark.req("FRG-SRC-010")
def test_the_trade_shape_designators_are_a_subset_of_what_the_strip_removes():
    """One vocabulary, one source: anything the shape detector treats as a
    volume/book designator must be boilerplate the strip removes, or the two
    would disagree about what the store title says."""
    from foragerr.sources.matching import (
        STRIP_DESIGNATORS,
        VOLUME_SHAPE_DESIGNATORS,
    )

    assert VOLUME_SHAPE_DESIGNATORS <= STRIP_DESIGNATORS
    assert VOLUME_SHAPE_DESIGNATORS  # ...and it is not vacuously empty


@pytest.mark.req("FRG-SRC-010")
def test_boilerplate_alone_never_opens_the_gate():
    """"Vane Vol. 1" vs "Argent Vol. 1" share ``vol`` and ``1`` on the raw fold.
    Post-strip they share nothing, so the gate — not the floor — refuses them."""
    assert not shares_token("Vane Vol. 1", "Argent Vol. 1")
    assert not shares_token("The Vants Vol. 1", "The Vints Vol. 1")
    # ...while a real shared word still opens it.
    assert shares_token("Vane Vol. 1", "Vane")


@pytest.mark.req("FRG-SRC-010")
async def test_boilerplate_overlap_neither_admits_nor_auto_accepts():
    """The two halves of the FRG-SRC-010 "boilerplate is not identity evidence"
    scenario, on the two verified repro pairs.

    "The Vants Vol. 1" vs "The Vints Vol. 1" scored 0.91 — over the auto-accept
    bar — off two shared boilerplate tokens and a single letter's difference.
    """
    vants = _FakeCV(candidates=[_cand(3001, "The Vints", 2010)])
    proposal = await compute_proposed_match(
        human_name="The Vants Vol. 1", library=[], cv_client=vants
    )
    # Not merely below the bar: nothing substantive is shared, so it is gated.
    _assert_no_plausible_match(proposal, universe=UNIVERSE_COMICVINE)
    assert title_confidence("The Vants Vol. 1", "The Vints Vol. 1") < (
        AUTO_MATCH_THRESHOLD
    )

    vane = _FakeCV(candidates=[_cand(4000, "Argent", 1940)])
    proposal = await compute_proposed_match(
        human_name="Vane Vol. 1", library=[], cv_client=vane
    )
    _assert_no_plausible_match(proposal, universe=UNIVERSE_COMICVINE)


@pytest.mark.req("FRG-SRC-010")
async def test_decorated_store_title_no_longer_floors_out_the_exact_volume():
    """The verified inversion (finding: "Vane Volume 1" floored its own answer).

    Raw scoring gave ComicVine's exact "Vane" 0.4706 — under the 0.5 floor —
    while the UNRELATED "Vane of the Sunken Reef" survived at 0.5625, purely
    because the decorated query is long and the right title is short. Stripped,
    the exact volume scores 1.0 and the stranger is floored.
    """
    cv = _FakeCV(
        candidates=[
            _cand(18975, "Vane", 2012),
            _cand(2001, "Vane of the Sunken Reef", 1982),
        ]
    )
    proposal = await compute_proposed_match(
        human_name="Vane Volume 1", library=[], cv_client=cv
    )
    assert proposal is not None
    assert proposal.best.cv_volume_id == 18975
    assert proposal.best.confidence == pytest.approx(1.0)
    assert 2001 not in {c.cv_volume_id for c in proposal.candidates}


@pytest.mark.req("FRG-SRC-010")
async def test_containment_keeps_the_exact_titled_volume_proposable():
    """FRG-SRC-010's "exact-titled volume survives a decorated store title".

    "Ashclaw" scores 0.4118 against the stripped "ashclaw fang of devastation"
    — length-asymmetric similarity buries it under the floor. Containment of
    the stripped canonical title inside the stripped query rescues it.
    """
    cv = _FakeCV(candidates=[_cand(10000, "Ashclaw", 1994)])
    proposal = await compute_proposed_match(
        human_name="Ashclaw Omnibus Volume 1: Fang of Devastation",
        library=[],
        cv_client=cv,
    )
    assert proposal is not None
    assert proposal.best.cv_volume_id == 10000
    assert proposal.best.confidence >= PROPOSE_MIN_SIMILARITY


@pytest.mark.req("FRG-SRC-010")
async def test_a_containment_rescue_proposes_but_never_auto_accepts():
    """Containment proves the store title DECORATES the candidate, which is
    plausibility, not identity — "Argent" is contained in "Argent and Shale"
    too. So a rescue is capped below the auto-accept bar, and an exact stripped
    equality (1.0) always outranks it."""
    assert MAX_CONTAINMENT_CONFIDENCE < AUTO_MATCH_THRESHOLD
    cv = _FakeCV(
        candidates=[
            _cand(2740, "The Duskman", 1989),
            _cand(44567, "The Duskman: Prologue", 2013),
        ]
    )
    proposal = await compute_proposed_match(
        human_name="The Duskman: Prologue", library=[], cv_client=cv
    )
    assert proposal is not None
    # The exact title wins outright; the contained parent is offered, capped.
    assert proposal.best.cv_volume_id == 44567
    assert proposal.best.confidence == pytest.approx(1.0)
    rescued = next(c for c in proposal.candidates if c.cv_volume_id == 2740)
    assert rescued.confidence == pytest.approx(MAX_CONTAINMENT_CONFIDENCE)
    assert rescued.confidence < AUTO_MATCH_THRESHOLD


@pytest.mark.req("FRG-SRC-010")
def test_token_gate_uses_the_shared_fold_and_ignores_articles():
    # "the" is dropped by matching_key on both sides, so it is never the token
    # that lets an unrelated candidate through.
    assert shares_token("Nobody is Guarding the Lighthouse", "The Lighthouse of Doom")
    assert not shares_token("Nobody is Guarding the Lighthouse", "The Amber Signal")
    assert not shares_token("Anything", None)


# --- the gate: the zero-overlap repro pair ----------------------------------


@pytest.mark.req("FRG-SRC-010")
async def test_zero_token_overlap_is_never_proposed_the_green_arrow_repro():
    """The zero-overlap repro shape (test-rig finding #7): an unrelated
    candidate scored 0.3673 against a long store title on a
    character-level ratio. Zero shared tokens ⇒ it is discarded BEFORE scoring,
    at any similarity, and the row carries the explicit no-match verdict."""
    cv = _FakeCV(candidates=[_cand(1, "Distant Amber Signal", 2024)])
    proposal = await compute_proposed_match(
        human_name="Nobody is Guarding the Lighthouse Vol. 8",
        library=_lib((7, "Distant Amber Signal", 2024, 1)),  # even if tracked
        cv_client=cv,
    )
    assert cv.calls == 1
    _assert_no_plausible_match(proposal, universe=UNIVERSE_COMICVINE)


@pytest.mark.req("FRG-SRC-010")
async def test_zero_overlap_gate_also_applies_to_the_library_fallback():
    proposal = await compute_proposed_match(
        human_name="Nobody is Guarding the Lighthouse Vol. 8",
        library=_lib((7, "Distant Amber Signal", 2024, 1)),
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
    catalog identity: a library series titled ``"Vane (2012)"`` for ComicVine's
    ``"Vane"`` must still be scored on the CV title.

    Applying the overlay before the gate scored the store title against the
    LOCAL title instead — 0.6154 here rather than 1.0 — silently dropping the
    row below the auto-match threshold and leaking shelf metadata into the
    CV-first gate."""
    cv = _FakeCV(candidates=[_cand(18975, "Vane", 2012)])
    proposal = await compute_proposed_match(
        human_name="Vane #1",
        library=_lib((7, "Vane (2012)", 2012, 18975)),
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
    assert proposal.best.title == "Vane (2012)"


@pytest.mark.req("FRG-SRC-010")
async def test_local_title_sharing_no_token_with_the_query_still_matches():
    """The extreme of the same bug: a library series renamed to something that
    shares NO token with the store title (a localized/alternate title) used to
    be discarded by the token gate — even though the ComicVine candidate it
    overlays matched the query exactly."""
    cv = _FakeCV(candidates=[_cand(18975, "Vane", 2012)])
    proposal = await compute_proposed_match(
        human_name="Vane #1",
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
    cv = _FakeCV(candidates=[_cand(1, "Distant Amber Signal", 2024)])
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
    """The shared collected-edition cue vocabulary decides the order. The
    singles line is still listed — a re-rank, never a filter.

    Both candidates now score 1.0, not 0.9091/0.8571, because the edition
    boilerplate they differ by (``vol 1`` / ``tpb``) is stripped before scoring
    — it was never identity evidence. The re-rank is what separates them, which
    is exactly the division of labour the design intended: similarity answers
    "same series?", the cue answers "which edition?".
    """
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
    # The re-rank is ordering-only: the reported confidence is still the plain
    # stripped similarity, unmultiplied by TRADE_RERANK_BOOST.
    assert proposal.best.confidence == pytest.approx(1.0)


@pytest.mark.req("FRG-SRC-010")
async def test_volume_ordinal_store_title_is_trade_shaped():
    """A bare "Vol 1" is a trade shape too — real collected editions
    overwhelmingly carry only the ordinal, never an explicit cue.

    REPLACES the old "singles-shaped control" reading of this title. Cue-only
    detection returned ``None`` for "Vane Vol. 1" / "Glasswing Book One" /
    "Ashclaw Omnibus Vol. 1" — i.e. for how store fronts actually name collected
    editions — so the trade re-rank never fired on the purchases it exists for.
    FRG-SRC-010 now counts a volume/book-ordinal shape as trade-shaped, and the
    collected candidate wins here as it does for the explicit-cue title above.
    """
    assert trade_shape("Synthetic Hero Vol 1") is not None
    assert trade_shape("Vane Vol. 1") is not None
    assert trade_shape("Glasswing Book One") is not None
    assert trade_shape("Ashclaw Omnibus Volume 1") is not None
    # ...but a SINGLE-issue designator is not a collection slice, so it must not
    # re-rank collected editions to the top.
    assert trade_shape("Synthetic Hero Issue 5") is None
    assert trade_shape("Synthetic Hero Chapter 3") is None
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
    assert proposal.best.cv_volume_id == 22


@pytest.mark.req("FRG-SRC-010")
async def test_singles_shaped_title_keeps_plain_similarity_order():
    """The control: a title with NEITHER a collected cue NOR a volume-ordinal
    shape is not trade-shaped, so the same two candidates rank on similarity
    alone and the boost never fires."""
    assert trade_shape("Synthetic Hero #1") is None
    cv = _FakeCV(
        candidates=[
            _cand(11, "Synthetic Hero Vol 1", 2018),
            _cand(22, "Synthetic Hero TPB", 2020),
        ]
    )
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero #1",
        library=[],
        cv_client=cv,
    )
    assert proposal is not None
    assert proposal.best.cv_volume_id == 11


@pytest.mark.req("FRG-SRC-010")
async def test_omnibus_counts_as_collected_on_both_sides_of_the_rerank():
    """"Omnibus" is stripped as boilerplate (both titles fold to the same key)
    but it is not in the parser cue vocabulary — without COLLECTED_STRIP_WORDS
    neither side of the re-rank sees it, the parent and the omnibus tie on
    stripped similarity, and the wrong shape can win on ordering. The
    omnibus store title must prefer the omnibus volume,
    with the bare parent still listed."""
    cv = _FakeCV(
        candidates=[
            _cand(31, "Ashclaw", 1994),  # bare parent line
            _cand(32, "Ashclaw Omnibus", 2018),  # collected edition
        ]
    )
    proposal = await compute_proposed_match(
        human_name="Ashclaw Omnibus Volume 1",
        library=[],
        cv_client=cv,
    )
    assert proposal is not None
    assert proposal.best.cv_volume_id == 32
    assert [c.cv_volume_id for c in proposal.candidates] == [32, 31]


@pytest.mark.req("FRG-SRC-010")
async def test_trade_rerank_cannot_resurrect_a_wrong_collected_edition():
    """The "Rook Hardcover" probe: the re-rank must not prefer a merely
    similar-but-different collected edition over the exact-titled series.

    Under raw scoring "Rook Handbook Hardcover" scored 0.76 against "Rook"'s
    0.44 and the 1.5625 boost window kept it in front. Stripped scoring closes
    it honestly — "Rook Handbook" is not the query, it is neither contained in
    it nor near it, so it never reaches the re-rank at all — which is why
    TRADE_RERANK_BOOST stays at 1.25.
    """
    cv = _FakeCV(
        candidates=[
            _cand(5000, "Rook", 1991),
            _cand(5001, "Rook Handbook Hardcover", 2010),
        ]
    )
    proposal = await compute_proposed_match(
        human_name="Rook Hardcover", library=[], cv_client=cv
    )
    assert proposal is not None
    assert proposal.best.cv_volume_id == 5000
    assert 5001 not in {c.cv_volume_id for c in proposal.candidates}


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


# --- the realistic 12-title corpus ------------------------------------------

#: Real-SHAPE store titles (synthetic names, live store idioms), each with the
#: ComicVine candidate pool the query would plausibly return, and the volume
#: that MUST be proposed. Every one of these is a shape the raw-fold scoring got
#: wrong in at least one direction (decorated query floors the exact volume;
#: boilerplate overlap admits a stranger; the singles line beats the collected
#: edition), so the corpus is the regression net for the whole overhaul rather
#: than a set of individual assertions.
#:
#: ``(store title, [(cv id, cv name, year), ...], expected cv id)``
REALISTIC_CORPUS = [
    # Decoration must not bury the exact-titled volume, and the near-namesake
    # ("Vane of the Sunken Reef") must not survive in its place.
    (
        "Vane Volume 1",
        [(18975, "Vane", 2012), (2001, "Vane of the Sunken Reef", 1982)],
        18975,
    ),
    (
        "Vane Vol. 3",
        [(18975, "Vane", 2012), (2001, "Vane of the Sunken Reef", 1982)],
        18975,
    ),
    # A subtitle plus a volume designator, against two same-word siblings.
    (
        "The Duskman Vol. 1: Whispers & Nightfall",
        [
            (2740, "The Duskman", 1989),
            (9999, "The Duskman Presents: Vespers", 1999),
            (8888, "Duskman Mystery Theatre", 1993),
        ],
        2740,
    ),
    # ...and the converse: a genuinely distinct sub-series is NOT the parent.
    (
        "The Duskman: Prologue",
        [(2740, "The Duskman", 1989), (44567, "The Duskman: Prologue", 2013)],
        44567,
    ),
    # Spelled-out ordinals are boilerplate too ("Book One").
    (
        "Glasswing Book One",
        [(89000, "Glasswing", 2015), (89001, "Glasswing: Side-Stories", 2021)],
        89000,
    ),
    (
        "Glasswing Volume 2: The Tides",
        [(89000, "Glasswing", 2015), (89001, "Glasswing: Side-Stories", 2021)],
        89000,
    ),
    # The containment scenario from the spec, and its discriminating sibling.
    (
        "Ashclaw Omnibus Volume 1: Fang of Devastation",
        [(10000, "Ashclaw", 1994), (10001, "Ashclaw in Ruin", 2012)],
        10000,
    ),
    (
        "Ashclaw in Ruin Volume 1",
        [(10000, "Ashclaw", 1994), (10001, "Ashclaw in Ruin", 2012)],
        10001,
    ),
    # A zero-overlap stranger ("Hallows") sits in the pool and must be gated.
    (
        "Hollow Vol. 1: Lantern in Exile",
        [
            (4600, "Hollow", 2002),
            (4601, "Hallows", 2012),
            (4602, "Hollow: The Silent Season", 2014),
        ],
        4600,
    ),
    # A named collected edition beats its own parent series.
    (
        "Hollow: The Deluxe Edition Book One",
        [(4600, "Hollow", 2002), (4603, "Hollow: The Deluxe Edition", 2009)],
        4603,
    ),
    # The print-year form, which only resolves once ``query_term`` re-strips.
    (
        "Ember (1992) #1",
        [(2010, "Ember", 1992), (2011, "Ember: The Unborn", 1999)],
        2010,
    ),
    (
        "Ember Origins Collection Vol. 1",
        [(2010, "Ember", 1992), (2012, "Ember Origins Collection", 2009)],
        2012,
    ),
]


@pytest.mark.req("FRG-SRC-010")
@pytest.mark.parametrize(
    ("human_name", "candidates", "expected_cv_id"),
    REALISTIC_CORPUS,
    ids=[row[0] for row in REALISTIC_CORPUS],
)
async def test_realistic_corpus_proposes_the_correct_volume(
    human_name, candidates, expected_cv_id
):
    cv = _FakeCV(candidates=[_cand(*c) for c in candidates])
    proposal = await compute_proposed_match(
        human_name=human_name, library=[], cv_client=cv
    )
    assert proposal is not None, f"{human_name!r} produced no proposal at all"
    assert proposal.best is not None, f"{human_name!r} got the no-match verdict"
    assert proposal.best.cv_volume_id == expected_cv_id


@pytest.mark.req("FRG-SRC-010")
def test_realistic_corpus_covers_the_shapes_the_gate_flagged():
    """A tripwire on the corpus itself: the six store shapes the length-asymmetry
    review sampled must all stay represented if this list is ever edited."""
    titles = " | ".join(row[0] for row in REALISTIC_CORPUS)
    for shape in ("Duskman", "Vane", "Glasswing", "Ashclaw", "Hollow", "Ember"):
        assert shape in titles
    assert len(REALISTIC_CORPUS) == 12


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
