"""Server-side proposed-match computation (FRG-SRC-004): library-first ranking,
ComicVine fallback, the auto-match confidence threshold, and clean budget defer.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from foragerr.metadata.errors import ComicVineBudgetExhausted
from foragerr.sources.matching import (
    AUTO_MATCH_THRESHOLD,
    LibrarySeriesLite,
    compute_proposed_match,
    query_term,
)


def _lib(*rows) -> list[LibrarySeriesLite]:
    return [LibrarySeriesLite(id=i, title=t, start_year=y) for i, t, y in rows]


class _FakeCV:
    """A ComicVine client stub exposing only ``suggest_series`` (what the ranker
    reads); candidates are namespaces with the three fields it uses."""

    def __init__(self, candidates=None, *, raises=None):
        self._candidates = candidates or []
        self._raises = raises
        self.calls = 0

    async def suggest_series(self, term):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return SimpleNamespace(candidates=self._candidates)


def _cand(cvid, name, year=None):
    return SimpleNamespace(cv_volume_id=cvid, name=name, start_year=year)


@pytest.mark.req("FRG-SRC-004")
def test_query_term_strips_issue_and_parenthetical():
    assert query_term("Synthetic Hero #1") == "Synthetic Hero"
    assert (
        query_term("Synthetic Hero Vol. 1 (collects #1-6)")
        == "Synthetic Hero Vol. 1"
    )


@pytest.mark.req("FRG-SRC-004")
async def test_library_match_wins_without_touching_comicvine():
    cv = _FakeCV(candidates=[_cand(999, "Totally Different Book")])
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero #1",
        library=_lib((7, "Synthetic Hero", 2018)),
        cv_client=cv,
    )
    assert proposal is not None
    assert proposal.best.kind == "library"
    assert proposal.best.series_id == 7
    assert proposal.proposed_series_id == 7
    assert proposal.confidence >= AUTO_MATCH_THRESHOLD
    assert proposal.is_auto is True
    # A confident library hit never consults ComicVine (budget politeness).
    assert cv.calls == 0


@pytest.mark.req("FRG-SRC-004")
async def test_comicvine_fallback_when_no_library_match():
    cv = _FakeCV(candidates=[_cand(4242, "Synthetic Hero", 2018)])
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero #1",
        library=_lib((1, "A Completely Unrelated Comic", 2001)),
        cv_client=cv,
    )
    assert cv.calls == 1
    assert proposal is not None
    assert proposal.best.kind == "comicvine"
    assert proposal.best.cv_volume_id == 4242
    assert proposal.proposed_series_id is None  # nothing local yet


@pytest.mark.req("FRG-SRC-004")
async def test_collected_edition_scores_below_auto_threshold():
    """A trade's long title must not silently auto-file into the singles run."""
    proposal = await compute_proposed_match(
        human_name="Synthetic Hero: The Collected Edition Vol. 1 (collects #1-6)",
        library=_lib((7, "Synthetic Hero", 2018)),
        cv_client=None,
    )
    assert proposal is not None
    assert proposal.confidence < AUTO_MATCH_THRESHOLD
    assert proposal.is_auto is False


@pytest.mark.req("FRG-SRC-004")
async def test_budget_exhausted_propagates_for_clean_defer():
    cv = _FakeCV(raises=ComicVineBudgetExhausted("volume", retry_after_seconds=60))
    with pytest.raises(ComicVineBudgetExhausted):
        await compute_proposed_match(
            human_name="Nothing Local Here #3",
            library=_lib((1, "Unrelated", 2000)),
            cv_client=cv,
        )


@pytest.mark.req("FRG-SRC-004")
async def test_no_pool_returns_none():
    proposal = await compute_proposed_match(
        human_name="Wholly Unknown Comic #1", library=[], cv_client=None
    )
    assert proposal is None
