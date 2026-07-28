"""Frugal, convergent proposal enrichment + the bulk recompute (FRG-SRC-013).

The failure this fixes is a scheduling one, not a matching one. Enrichment used
to walk its pending set oldest-id-FIRST, so a run that ran out of ComicVine
budget (or kept erroring) at the head restarted at the same rows the next night
and the tail was never reached at all — on the live rig's 1,318-row source that
is a queue that never converges.

The fix is an attempt stamp on every row a run TOUCHES and a walk ordered
never-attempted-first, then oldest-attempt-first. Two properties are load-bearing
and tested here:

* the stamp orders work and NOTHING else. A budget-deferred row still has a NULL
  proposal and is still eligible — the FRG-SRC-010 invariant — it has merely
  moved behind the rows this run never reached;
* only ERRORED rows are additionally spaced out, and only on the scheduled path;
  a budget deferral is a window refusal, not a failure of the row, and every
  operator-initiated path ignores the spacing entirely.

The bulk recompute is the operator-triggered half: it refreshes proposals stored
before the ComicVine-first universe existed (which, being non-NULL, can never
re-enter the enrichment pass), stops cleanly at the budget wall with a prefix
refreshed and every unreached row's existing proposal intact, and resumes from
the same ordering when re-run.
"""

from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.db.base import utcnow
from foragerr.metadata.errors import ComicVineBudgetExhausted, ComicVineError
from foragerr.sources import ratelimit, repo
from foragerr.sources.enrich import (
    enrich_source,
    is_library_fallback_marker,
    is_recompute_target,
    predates_cv_universe,
    recompute_proposals,
)
from foragerr.sources.matching import (
    UNIVERSE_COMICVINE,
    UNIVERSE_LIBRARY_FALLBACK,
    VERDICT_NO_PLAUSIBLE_MATCH,
)
from foragerr.sources.models import SourceEntitlementRow
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.settings import HumbleSettings
from http_support import make_settings
from sources_support import fixture_bytes, make_factory, order_handler

# --- doubles ----------------------------------------------------------------


class _FakeCV:
    """A ComicVine client that answers, errors or hits the budget wall on cue.

    ``budget`` is the number of ANSWERS this client has in it; the call after
    that raises :class:`ComicVineBudgetExhausted`, which is how a real run meets
    the wall mid-batch. ``fail_terms`` names terms whose call raises a plain
    ComicVineError (an upstream blip, not a budget refusal) — the two must not be
    treated alike.
    """

    def __init__(self, *, budget: int | None = None, fail_terms=()):
        self.budget = budget
        self.fail_terms = set(fail_terms)
        self.terms: list[str] = []

    async def suggest_series(self, term):
        if self.budget is not None and len(self.terms) >= self.budget:
            raise ComicVineBudgetExhausted("volume", retry_after_seconds=60)
        self.terms.append(term)
        if any(f in term for f in self.fail_terms):
            raise ComicVineError("upstream 500")
        return SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    cv_volume_id=777, name="Synthetic Hero", start_year=2018
                )
            ]
        )

    async def aclose(self):
        pass


#: A proposal in the PRE-v0.11 stored shape: ranked against the local library
#: before ComicVine became the matching universe, and therefore carrying no
#: ``universe`` key at all. That absence is the only signature of staleness.
LEGACY_PROPOSAL = json.dumps(
    {
        "auto": False,
        "candidates": [],
        "confidence": 0.51,
        "cv_volume_id": None,
        "kind": "library",
        "series_id": None,
        "title": "An Old Shelf-Local Guess",
        "year": None,
    },
    sort_keys=True,
)

FALLBACK_MARKER = json.dumps(
    {
        "auto": False,
        "candidates": [],
        "universe": UNIVERSE_LIBRARY_FALLBACK,
        "verdict": VERDICT_NO_PLAUSIBLE_MATCH,
    },
    sort_keys=True,
)

CV_MARKER = json.dumps(
    {
        "auto": False,
        "candidates": [],
        "universe": UNIVERSE_COMICVINE,
        "verdict": VERDICT_NO_PLAUSIBLE_MATCH,
    },
    sort_keys=True,
)


async def _source(db, *, auto_sync: bool = False):
    return await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Humble",
        settings=HumbleSettings(session_cookie="C"),
        connection_state="connected",
        auto_sync=auto_sync,
    )


async def _comic(
    db,
    source_id: int,
    human_name: str,
    machine_name: str,
    *,
    proposal: str | None = None,
    attempted_at: dt.datetime | None = None,
    errored: bool | None = None,
    review_status: str = "new",
) -> int:
    now = utcnow()
    async with db.write_session() as session:
        row = SourceEntitlementRow(
            source_id=source_id,
            gamekey="gk",
            machine_name=machine_name,
            human_name=human_name,
            publisher=None,
            classification="comic",
            review_status=review_status,
            download_state=None,
            md5="a" * 32,
            file_size=1,
            filename="x.cbz",
            proposed_match_json=proposal,
            proposal_attempted_at=attempted_at,
            proposal_attempt_error=errored,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _row(db, eid: int) -> SourceEntitlementRow:
    return await repo.get_entitlement(db, eid)


# --- ordering: a failing head cannot starve the tail -------------------------


@pytest.mark.req("FRG-SRC-013")
async def test_a_failing_head_cannot_starve_the_tail(db, config_dir):
    """Two budget-limited runs over three rows. The old oldest-id-first walk
    spent both runs on the same head and never looked at the tail; the attempt
    order spends run 2 on the row run 1 never reached."""
    source = await _source(db)
    settings = make_settings(config_dir)
    ids = [
        await _comic(db, source.id, "Synthetic Hero #1", "a"),
        await _comic(db, source.id, "Synthetic Hero #2", "b"),
        await _comic(db, source.id, "Synthetic Hero #3", "c"),
    ]

    # Run 1: one answer in the budget — row a is proposed, row b meets the wall,
    # row c is never reached.
    first = _FakeCV(budget=1)
    await enrich_source(db, settings, source, cv_client=first)
    assert first.terms == ["Synthetic Hero"]  # the head only
    assert (await _row(db, ids[0])).proposed_match_json is not None
    assert (await _row(db, ids[1])).proposed_match_json is None
    assert (await _row(db, ids[2])).proposed_match_json is None
    # The wall row was TOUCHED (stamped) and the unreached row was not.
    assert (await _row(db, ids[1])).proposal_attempted_at is not None
    assert (await _row(db, ids[2])).proposal_attempted_at is None

    # Run 2, same budget: the never-attempted TAIL goes first, not the head.
    second = _FakeCV(budget=1)
    await enrich_source(db, settings, source, cv_client=second)
    assert (await _row(db, ids[2])).proposed_match_json is not None
    # ...and row b — attempted, deferred — waits its turn rather than eating the
    # whole window again.
    assert (await _row(db, ids[1])).proposed_match_json is None

    # Run 3 finally reaches it: the queue CONVERGES instead of grinding a head.
    await enrich_source(db, settings, source, cv_client=_FakeCV(budget=1))
    assert (await _row(db, ids[1])).proposed_match_json is not None


@pytest.mark.req("FRG-SRC-013")
async def test_a_deferral_stamp_advances_the_restart_position(db, config_dir):
    """The stamp on a budget-deferred row is what moves the next run's starting
    point forward. Nothing is ever answered here — every run meets the wall on
    its first row — so the ONLY evidence of progress is which row each run
    touched, and that is exactly the property under test."""
    source = await _source(db)
    settings = make_settings(config_dir)
    alpha = await _comic(db, source.id, "Alpha Title #1", "a")
    beta = await _comic(db, source.id, "Beta Title #1", "b")

    await enrich_source(db, settings, source, cv_client=_FakeCV(budget=0))
    first_alpha = (await _row(db, alpha)).proposal_attempted_at
    assert first_alpha is not None
    assert (await _row(db, beta)).proposal_attempted_at is None  # never reached
    # The work order for the next run already puts the unreached row first.
    ordered = await repo.list_entitlements(
        db, source.id, review_status="new", order_by_attempt=True
    )
    assert [r.human_name for r in ordered] == ["Beta Title #1", "Alpha Title #1"]

    await enrich_source(db, settings, source, cv_client=_FakeCV(budget=0))
    beta_stamp = (await _row(db, beta)).proposal_attempted_at
    # Run 2 spent its (empty) window on BETA — the row run 1 never reached —
    # rather than grinding Alpha again; Alpha's stamp is untouched.
    assert beta_stamp is not None
    assert (await _row(db, alpha)).proposal_attempted_at == first_alpha
    assert beta_stamp >= first_alpha
    # ...and the order now round-robins back to Alpha: no row can monopolise the
    # head, and none can be starved out of the tail.
    ordered = await repo.list_entitlements(
        db, source.id, review_status="new", order_by_attempt=True
    )
    assert [r.human_name for r in ordered] == ["Alpha Title #1", "Beta Title #1"]


@pytest.mark.req("FRG-SRC-010")
async def test_a_deferral_stamp_never_gates_eligibility(db, config_dir):
    """FRG-SRC-010 non-regression: the new stamp changes ORDER, never
    eligibility. A budget-deferred row keeps a NULL proposal, keeps its ``new``
    status, is not flagged as errored (so no spacing applies to it), and is
    proposed by the very next run."""
    source = await _source(db)
    settings = make_settings(config_dir)
    eid = await _comic(db, source.id, "Synthetic Hero #1", "a")

    await enrich_source(db, settings, source, cv_client=_FakeCV(budget=0))
    deferred = await _row(db, eid)
    assert deferred.proposed_match_json is None
    assert deferred.review_status == "new"
    assert deferred.proposal_attempted_at is not None
    assert deferred.proposal_attempt_error is False  # deferral is NOT an error

    await enrich_source(db, settings, source, cv_client=_FakeCV())
    assert (await _row(db, eid)).proposed_match_json is not None


# --- CV-error spacing --------------------------------------------------------


@pytest.mark.req("FRG-SRC-013")
async def test_an_errored_row_is_spaced_out_on_the_scheduled_path(db, config_dir):
    """A row ComicVine keeps failing on is re-asked once a day, not once a run.
    The budget it stops burning is budget the rest of the backlog gets."""
    source = await _source(db)
    settings = make_settings(config_dir)  # default spacing: one day
    eid = await _comic(db, source.id, "Cursed Title #1", "a")

    first = _FakeCV(fail_terms=["Cursed"])
    await enrich_source(db, settings, source, cv_client=first)
    errored = await _row(db, eid)
    assert errored.proposed_match_json is None  # an error is a deferral, no verdict
    assert errored.proposal_attempt_error is True

    second = _FakeCV(fail_terms=["Cursed"])
    summary = await enrich_source(db, settings, source, cv_client=second)
    assert second.terms == []  # not re-asked this run
    assert "1 spaced" in summary  # counted, never silently dropped

    # The row is still ELIGIBLE — spacing is a wait, not a verdict: once the
    # spacing elapses (here, by configuration) the retry happens.
    relaxed = make_settings(config_dir, comicvine_error_retry_spacing_seconds=0)
    third = _FakeCV()
    await enrich_source(db, relaxed, source, cv_client=third)
    assert third.terms == ["Cursed Title"]
    assert (await _row(db, eid)).proposed_match_json is not None


@pytest.mark.req("FRG-SRC-013")
async def test_spacing_never_holds_back_a_budget_deferred_row(db, config_dir):
    """Only errors are spaced. Spacing a row the budget wall deferred would turn
    a rolling-window refusal into a day-long freeze — the opposite of frugal."""
    source = await _source(db)
    settings = make_settings(config_dir)
    eid = await _comic(db, source.id, "Synthetic Hero #1", "a")

    await enrich_source(db, settings, source, cv_client=_FakeCV(budget=0))
    again = _FakeCV()
    await enrich_source(db, settings, source, cv_client=again)
    assert again.terms == ["Synthetic Hero"]  # retried immediately, no wait
    assert (await _row(db, eid)).proposed_match_json is not None


@pytest.mark.req("FRG-SRC-013")
async def test_the_operator_restore_path_ignores_the_spacing(db, config_dir):
    """The operator asking IS the retry decision: restore recomputes a
    freshly-errored row without waiting out the spacing window."""
    from foragerr.sources import review

    source = await _source(db)
    eid = await _comic(
        db,
        source.id,
        "Synthetic Hero #1",
        "a",
        attempted_at=utcnow(),
        errored=True,
        review_status="ignored",
    )

    restored = await review.restore_entitlement(
        db, eid, cv_client=_FakeCV(), cv_configured=True
    )
    assert restored.review_status == "new"
    assert restored.proposed_match_json is not None
    assert json.loads(restored.proposed_match_json)["universe"] == UNIVERSE_COMICVINE


# --- key transition: library-fallback markers rejoin the pending set ---------


@pytest.mark.req("FRG-SRC-013")
async def test_library_fallback_markers_become_pending_once_a_key_exists(
    db, config_dir
):
    """A marker computed with no ComicVine key says "nothing on your SHELF looks
    like this" — a verdict about the wrong universe, and one that froze the row
    out of every later pass. With a key configured it is a question worth asking
    again."""
    source = await _source(db)
    settings = make_settings(config_dir)
    eid = await _comic(
        db, source.id, "Synthetic Hero #1", "a", proposal=FALLBACK_MARKER
    )

    cv = _FakeCV()
    await enrich_source(db, settings, source, cv_client=cv)
    assert cv.terms == ["Synthetic Hero"]
    refreshed = json.loads((await _row(db, eid)).proposed_match_json)
    assert refreshed["universe"] == UNIVERSE_COMICVINE
    assert refreshed["cv_volume_id"] == 777


@pytest.mark.req("FRG-SRC-013")
async def test_an_unconfigured_deployment_leaves_its_own_markers_alone(
    db, config_dir
):
    """Without a key the fallback marker IS the honest answer — recomputing it
    would spend nothing and change nothing, so it stays out of the pending set."""
    source = await _source(db)
    eid = await _comic(
        db, source.id, "Synthetic Hero #1", "a", proposal=FALLBACK_MARKER
    )

    await enrich_source(db, make_settings(config_dir), source, cv_client=None)
    row = await _row(db, eid)
    assert row.proposed_match_json == FALLBACK_MARKER
    assert row.proposal_attempted_at is None  # never touched


@pytest.mark.req("FRG-SRC-013")
async def test_a_comicvine_marker_is_a_real_verdict_and_stays_put(db, config_dir):
    """Only the KEYLESS marker is revisited. A marker ComicVine itself produced
    is an answer, not a gap, and re-asking it every night is exactly the spend
    this change exists to stop."""
    source = await _source(db)
    eid = await _comic(db, source.id, "Synthetic Hero #1", "a", proposal=CV_MARKER)

    cv = _FakeCV()
    await enrich_source(db, make_settings(config_dir), source, cv_client=cv)
    assert cv.terms == []
    assert (await _row(db, eid)).proposed_match_json == CV_MARKER


# --- stored-shape detection --------------------------------------------------


@pytest.mark.req("FRG-SRC-013")
def test_pre_universe_shape_detection_reads_the_missing_universe_key():
    """``universe`` arrived WITH the ComicVine-first ranking, so its absence —
    and nothing else — identifies a proposal ranked before it existed."""
    assert predates_cv_universe(LEGACY_PROPOSAL) is True
    assert predates_cv_universe(CV_MARKER) is False
    assert predates_cv_universe(FALLBACK_MARKER) is False
    assert predates_cv_universe(None) is False
    assert predates_cv_universe("not json at all") is False

    assert is_library_fallback_marker(FALLBACK_MARKER) is True
    assert is_library_fallback_marker(CV_MARKER) is False
    assert is_library_fallback_marker(LEGACY_PROPOSAL) is False

    stale = SimpleNamespace(proposed_match_json=LEGACY_PROPOSAL)
    marker = SimpleNamespace(proposed_match_json=CV_MARKER)
    unproposed = SimpleNamespace(proposed_match_json=None)
    assert is_recompute_target(stale, include_markers=False) is True
    assert is_recompute_target(marker, include_markers=False) is False
    assert is_recompute_target(marker, include_markers=True) is True
    # A row with no proposal belongs to the enrichment pass, not to recompute —
    # targeting it here would spend the same budget twice on one backlog.
    assert is_recompute_target(unproposed, include_markers=True) is False


# --- bulk recompute ----------------------------------------------------------


@pytest.mark.req("FRG-SRC-013")
async def test_recompute_is_resumable_across_a_budget_refusal(db, config_dir):
    """The spec scenario: a large source, the wall mid-walk. A prefix is
    refreshed, no row loses its existing proposal to the interruption, and
    re-running continues from the least-recently-attempted rows."""
    source = await _source(db)
    settings = make_settings(config_dir)
    ids = [
        await _comic(db, source.id, "Synthetic Hero #1", "a", proposal=LEGACY_PROPOSAL),
        await _comic(db, source.id, "Synthetic Hero #2", "b", proposal=LEGACY_PROPOSAL),
        await _comic(db, source.id, "Synthetic Hero #3", "c", proposal=LEGACY_PROPOSAL),
    ]

    summary = await recompute_proposals(
        db, settings, source, cv_client=_FakeCV(budget=1)
    )
    assert "1 refreshed" in summary
    assert "budget exhausted" in summary
    assert "re-run to resume" in summary

    first = await _row(db, ids[0])
    assert json.loads(first.proposed_match_json)["universe"] == UNIVERSE_COMICVINE
    # Everything the walk did not finish KEEPS its existing proposal: a stale
    # proposal is still a proposal, and losing it would empty the review screen.
    assert (await _row(db, ids[1])).proposed_match_json == LEGACY_PROPOSAL
    assert (await _row(db, ids[2])).proposed_match_json == LEGACY_PROPOSAL

    # Re-run: it resumes at the rows it never refreshed, not back at the top.
    second = _FakeCV()
    tail = await recompute_proposals(db, settings, source, cv_client=second)
    assert second.terms == ["Synthetic Hero", "Synthetic Hero"]  # the two remaining
    assert "2 refreshed" in tail
    assert "0 remaining" in tail
    for eid in ids:
        stored = json.loads((await _row(db, eid)).proposed_match_json)
        assert stored["universe"] == UNIVERSE_COMICVINE

    # Idempotent at the end: nothing is stale, so nothing is spent.
    idle = _FakeCV()
    assert "0 refreshed" in await recompute_proposals(
        db, settings, source, cv_client=idle
    )
    assert idle.terms == []


@pytest.mark.req("FRG-SRC-013")
async def test_recompute_never_touches_operator_decisions(db, config_dir):
    """Matched and ignored rows are DECISIONS (FRG-SRC-008/012 stickiness). A
    bulk action that walked past them re-proposing would be the change quietly
    second-guessing the operator."""
    source = await _source(db)
    matched = await _comic(
        db,
        source.id,
        "Synthetic Hero #1",
        "a",
        proposal=LEGACY_PROPOSAL,
        review_status="matched",
    )
    ignored = await _comic(
        db,
        source.id,
        "Synthetic Hero #2",
        "b",
        proposal=LEGACY_PROPOSAL,
        review_status="ignored",
    )
    reviewable = await _comic(
        db, source.id, "Synthetic Hero #3", "c", proposal=LEGACY_PROPOSAL
    )

    cv = _FakeCV()
    summary = await recompute_proposals(
        db, make_settings(config_dir), source, cv_client=cv
    )
    assert "1 refreshed" in summary
    assert cv.terms == ["Synthetic Hero"]  # exactly one row consulted
    assert (await _row(db, matched)).proposed_match_json == LEGACY_PROPOSAL
    assert (await _row(db, matched)).review_status == "matched"
    assert (await _row(db, ignored)).proposed_match_json == LEGACY_PROPOSAL
    assert (await _row(db, ignored)).review_status == "ignored"
    assert (await _row(db, reviewable)).proposed_match_json != LEGACY_PROPOSAL


@pytest.mark.req("FRG-SRC-013")
async def test_recompute_of_markers_is_opt_in(db, config_dir):
    source = await _source(db)
    settings = make_settings(config_dir)
    eid = await _comic(db, source.id, "Synthetic Hero #1", "a", proposal=CV_MARKER)

    quiet = _FakeCV()
    await recompute_proposals(db, settings, source, cv_client=quiet)
    assert quiet.terms == []
    assert (await _row(db, eid)).proposed_match_json == CV_MARKER

    asked = _FakeCV()
    await recompute_proposals(
        db, settings, source, include_markers=True, cv_client=asked
    )
    assert asked.terms == ["Synthetic Hero"]
    assert json.loads((await _row(db, eid)).proposed_match_json)["cv_volume_id"] == 777


@pytest.mark.req("FRG-SRC-013")
async def test_a_per_row_comicvine_error_does_not_end_the_recompute(db, config_dir):
    """One unanswerable title is not a reason to abandon the batch — unlike the
    budget wall, which is."""
    source = await _source(db)
    cursed = await _comic(
        db, source.id, "Cursed Title #1", "a", proposal=LEGACY_PROPOSAL
    )
    ok = await _comic(
        db, source.id, "Synthetic Hero #1", "b", proposal=LEGACY_PROPOSAL
    )

    summary = await recompute_proposals(
        db,
        make_settings(config_dir),
        source,
        cv_client=_FakeCV(fail_terms=["Cursed"]),
    )
    assert "1 refreshed" in summary
    assert "1 errored" in summary
    assert (await _row(db, cursed)).proposed_match_json == LEGACY_PROPOSAL
    assert (await _row(db, cursed)).proposal_attempt_error is True
    assert json.loads((await _row(db, ok)).proposed_match_json)["cv_volume_id"] == 777


@pytest.mark.req("FRG-SRC-013")
async def test_recompute_refuses_to_run_without_a_comicvine_key(db, config_dir):
    """Recomputing library-only would REPLACE catalog-shaped proposals with
    shelf-local guesses — strictly backwards, so it does not happen."""
    source = await _source(db)
    eid = await _comic(
        db, source.id, "Synthetic Hero #1", "a", proposal=LEGACY_PROPOSAL
    )

    summary = await recompute_proposals(db, make_settings(config_dir), source)
    assert "not configured" in summary
    assert (await _row(db, eid)).proposed_match_json == LEGACY_PROPOSAL


# --- the operator endpoint ---------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


@pytest.fixture
def client(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(make_settings(cfg))
    app.state.http_factory = make_factory(
        tmp_path,
        httpx.MockTransport(
            order_handler(
                list_body=fixture_bytes("order_list.json"),
                order_bodies={"default": fixture_bytes("order_comics.json")},
            )
        ),
    )
    with TestClient(app) as c:
        yield c


def _connected_source_id(client) -> int:
    created = client.post(
        "/api/v1/sources",
        json={"type": "humble", "settings": {"session_cookie": "PASTED-COOKIE"}},
    ).json()
    return created["source"]["id"]


@pytest.mark.req("FRG-SRC-013")
def test_recompute_endpoint_enqueues_the_command(client):
    source_id = _connected_source_id(client)

    resp = client.post(f"/api/v1/sources/{source_id}/recompute-proposals")
    assert resp.status_code == 202
    assert "command_id" in resp.json()

    # The marker opt-in is a body flag, and it is a DIFFERENT payload — so it
    # enqueues its own run rather than being deduped onto the default one.
    opted = client.post(
        f"/api/v1/sources/{source_id}/recompute-proposals",
        json={"include_markers": True},
    )
    assert opted.status_code == 202


@pytest.mark.req("FRG-SRC-013")
def test_recompute_endpoint_404s_on_an_unknown_source(client):
    assert (
        client.post("/api/v1/sources/9999/recompute-proposals").status_code == 404
    )
