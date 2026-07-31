"""Budget deferral vs. the no-plausible-match verdict (FRG-SRC-004/010).

Two states look alike on a row and must not be confused:

* **deferred** — the computation could not run (the ComicVine budget was
  exhausted, or CV failed). The row keeps a NULL ``proposed_match_json`` and is
  picked up again by the next sync. Nothing library-only is computed, persisted
  or auto-accepted in its place: a fallback proposal would freeze the row out of
  the pending set forever, so the deferred CV lookup would never happen — and at
  ``auto_sync`` ON it could accept and download against a shelf-local guess.
* **no plausible match** — the computation RAN and found nothing. The row is
  stamped with the explicit marker, so the review UI can distinguish it from a
  row nothing has looked at yet.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from foragerr.db.base import utcnow
from foragerr.library import repo as library_repo
from foragerr.metadata.errors import ComicVineBudgetExhausted, ComicVineError
from foragerr.sources import repo
from foragerr.sources.enrich import enrich_source
from foragerr.sources.matching import (
    UNIVERSE_COMICVINE,
    VERDICT_NO_PLAUSIBLE_MATCH,
)
from foragerr.sources.models import SourceEntitlementRow
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.settings import HumbleSettings
from http_support import make_settings
from sources_support import (  # noqa: F401 — imported fixtures
    FakeCommands,
    format_profile_id,
    root_folder_id,
)


class _FakeCV:
    def __init__(self, candidates=None, *, raises=None):
        self._candidates = candidates or []
        self._raises = raises
        self.calls = 0

    async def suggest_series(self, term):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return SimpleNamespace(candidates=self._candidates)

    async def aclose(self):
        pass


def _budget_exhausted() -> _FakeCV:
    return _FakeCV(raises=ComicVineBudgetExhausted("volume", retry_after_seconds=60))


def _cand(cvid, name, year=None):
    return SimpleNamespace(cv_volume_id=cvid, name=name, start_year=year)


async def _new_comic(db, source_id, human_name, machine_name="mn") -> int:
    now = utcnow()
    async with db.write_session() as session:
        row = SourceEntitlementRow(
            source_id=source_id,
            gamekey="gk",
            machine_name=machine_name,
            human_name=human_name,
            publisher=None,
            classification="comic",
            review_status="new",
            download_state=None,
            md5="a" * 32,
            file_size=1,
            filename="x.cbz",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _source(db, *, auto_sync: bool = False):
    return await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Humble",
        settings=HumbleSettings(session_cookie="C"),
        connection_state="connected",
        auto_sync=auto_sync,
    )


async def _series(db, root_folder_id, format_profile_id, *, cvid, title, path):
    async with db.write_session() as session:
        await library_repo.create_series(
            session,
            cv_volume_id=cvid,
            title=title,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=path,
        )


# --- deferral: a budget hit writes NOTHING -----------------------------------


@pytest.mark.req("FRG-SRC-004")
async def test_budget_exhausted_weak_library_item_is_retried_next_sync(
    db, config_dir, root_folder_id, format_profile_id
):
    source = await _source(db)
    # A weak-only library candidate (~0.39 vs the entitlement title) so the
    # ranker must consult CV — where the budget will be exhausted.
    await _series(
        db,
        root_folder_id,
        format_profile_id,
        cvid=42,
        title="Detective Comics Weekly",
        path="/tmp/comics/dcw",
    )
    eid = await _new_comic(db, source.id, "Obscure Chronicles #1")
    settings = make_settings(config_dir)

    # First sync: CV budget exhausted → the weak library guess is NOT frozen.
    await enrich_source(db, settings, source, cv_client=_budget_exhausted())
    after_first = await repo.get_entitlement(db, eid)
    assert after_first.proposed_match_json is None  # left retryable, not stamped

    # Next sync: budget recovered → the deferred CV lookup runs and a match lands.
    await enrich_source(
        db,
        settings,
        source,
        cv_client=_FakeCV(candidates=[_cand(777, "Obscure Chronicles", 2015)]),
    )
    after_second = await repo.get_entitlement(db, eid)
    assert after_second.proposed_match_json is not None
    assert '"cv_volume_id": 777' in after_second.proposed_match_json


@pytest.mark.req("FRG-SRC-004")
async def test_budget_exhausted_does_not_freeze_a_CONFIDENT_library_row(
    db, config_dir, root_folder_id, format_profile_id
):
    """The finding: a budget-window recompute used to persist a CONFIDENT
    library-only proposal (it cleared the auto-match threshold, so the old
    "weak-only" guard let it through) — freezing the row and, at ``auto_sync``
    ON, accepting and downloading against a shelf-local guess. FRG-SRC-010 says
    budget exhaustion leaves affected rows un-proposed and retryable, full stop:
    confidence is not the discriminator, the missing CV verdict is."""
    source = await _source(db)
    await _series(
        db,
        root_folder_id,
        format_profile_id,
        cvid=42,
        title="Synthetic Hero",
        path="/tmp/comics/sh",
    )
    eid = await _new_comic(db, source.id, "Synthetic Hero #1")
    settings = make_settings(config_dir)

    summary = await enrich_source(db, settings, source, cv_client=_budget_exhausted())
    after = await repo.get_entitlement(db, eid)
    assert after.proposed_match_json is None  # not the library fallback, NULL
    assert after.proposed_series_id is None
    assert after.review_status == "new"
    assert "1 deferred" in summary

    # And the next sync — CV answering now — lands the catalog verdict.
    await enrich_source(
        db,
        settings,
        source,
        cv_client=_FakeCV(candidates=[_cand(42, "Synthetic Hero", 2018)]),
    )
    recovered = json.loads(
        (await repo.get_entitlement(db, eid)).proposed_match_json
    )
    assert recovered["universe"] == UNIVERSE_COMICVINE
    assert recovered["kind"] == "library"  # the overlay: it IS already tracked
    assert recovered["cv_volume_id"] == 42


@pytest.mark.req("FRG-SRC-004")
async def test_budget_hit_stops_the_batch_leaving_later_rows_retryable(
    db, config_dir, root_folder_id, format_profile_id
):
    """The wall is per-run, not per-item: rows after the exhausting one are not
    quietly downgraded to a library-only ranking either."""
    source = await _source(db)
    await _series(
        db,
        root_folder_id,
        format_profile_id,
        cvid=42,
        title="Synthetic Hero",
        path="/tmp/comics/sh",
    )
    ids = [
        await _new_comic(db, source.id, "Synthetic Hero #1", machine_name="a"),
        await _new_comic(db, source.id, "Synthetic Hero #2", machine_name="b"),
        await _new_comic(db, source.id, "Synthetic Hero #3", machine_name="c"),
    ]

    await enrich_source(
        db, make_settings(config_dir), source, cv_client=_budget_exhausted()
    )
    for eid in ids:
        row = await repo.get_entitlement(db, eid)
        assert row.proposed_match_json is None
        assert row.review_status == "new"


@pytest.mark.req("FRG-SRC-004")
async def test_auto_sync_accepts_nothing_from_a_budget_hit_window(
    db, config_dir, root_folder_id, format_profile_id
):
    """Auto-accept never fires from a ``library-fallback`` ranking on a
    CV-configured run: with ``auto_sync`` ON and the budget exhausted, a library
    series that would confidently match is neither proposed nor accepted, and no
    grab is queued."""
    source = await _source(db, auto_sync=True)
    await _series(
        db,
        root_folder_id,
        format_profile_id,
        cvid=42,
        title="Synthetic Hero",
        path="/tmp/comics/sh",
    )
    eid = await _new_comic(db, source.id, "Synthetic Hero #1")
    commands = FakeCommands()

    summary = await enrich_source(
        db,
        make_settings(config_dir),
        source,
        commands=commands,
        cv_client=_budget_exhausted(),
    )
    assert "auto_sync=on" in summary
    assert "0 auto-accepted" in summary
    assert commands.enqueued == []
    after = await repo.get_entitlement(db, eid)
    assert after.review_status == "new"
    assert after.matched_series_id is None
    assert after.matched_via is None
    assert after.download_state is None
    assert after.proposed_match_json is None


@pytest.mark.req("FRG-SRC-004")
async def test_a_failed_comicvine_call_also_leaves_the_row_retryable(
    db, config_dir, root_folder_id, format_profile_id
):
    """A CV 500 is a deferral, not a verdict — no marker is written."""
    source = await _source(db)
    eid = await _new_comic(db, source.id, "Synthetic Hero #1")

    await enrich_source(
        db,
        make_settings(config_dir),
        source,
        cv_client=_FakeCV(raises=ComicVineError("upstream 500")),
    )
    assert (await repo.get_entitlement(db, eid)).proposed_match_json is None


# --- the no-plausible-match verdict -----------------------------------------


@pytest.mark.req("FRG-SRC-010")
async def test_genuine_no_match_persists_the_explicit_verdict_marker(
    db, config_dir, root_folder_id, format_profile_id
):
    """ComicVine answered and nothing cleared the gate/floor: the row records
    the verdict, so the UI can tell it apart from a never-computed NULL."""
    source = await _source(db)
    eid = await _new_comic(db, source.id, "Nobody is Guarding the Lighthouse Vol. 8")

    await enrich_source(
        db,
        make_settings(config_dir),
        source,
        cv_client=_FakeCV(candidates=[_cand(1, "Distant Amber Signal", 2024)]),
    )
    row = await repo.get_entitlement(db, eid)
    assert row.proposed_match_json is not None
    assert row.proposed_series_id is None
    assert row.review_status == "new"  # a verdict, never a terminal state
    assert json.loads(row.proposed_match_json) == {
        "verdict": VERDICT_NO_PLAUSIBLE_MATCH,
        "universe": UNIVERSE_COMICVINE,
        "candidates": [],
        "auto": False,
    }


@pytest.mark.req("FRG-SRC-010")
async def test_the_marker_is_never_auto_accepted(
    db, config_dir, root_folder_id, format_profile_id
):
    source = await _source(db, auto_sync=True)
    eid = await _new_comic(db, source.id, "Nobody is Guarding the Lighthouse Vol. 8")
    commands = FakeCommands()

    summary = await enrich_source(
        db,
        make_settings(config_dir),
        source,
        commands=commands,
        cv_client=_FakeCV(candidates=[_cand(1, "Distant Amber Signal", 2024)]),
    )
    assert "0 auto-accepted" in summary
    assert commands.enqueued == []
    assert (await repo.get_entitlement(db, eid)).review_status == "new"


@pytest.mark.req("FRG-SRC-004")
async def test_auto_accept_skips_a_row_decided_while_the_run_was_working(
    db, config_dir, root_folder_id, format_profile_id
):
    """``proposals`` is a snapshot taken before the persist + accept run, and
    the operator is looking at the same queue. A row ignored (or matched) by
    hand mid-run is a DECISION, and auto-sync must not walk over it with a
    proposal computed before that decision existed — it would resurrect the row
    to ``matched`` and enqueue the grab the operator just withdrew.

    Simulated at the seam it actually races: ``_auto_accept`` is handed the
    proposal map after the row has been decided, exactly as it would be if the
    ignore had committed during the persist pass.
    """
    from foragerr.sources import review
    from foragerr.sources.enrich import _auto_accept
    from foragerr.sources.matching import MatchCandidate, ProposedMatch

    source = await _source(db, auto_sync=True)
    await _series(
        db,
        root_folder_id,
        format_profile_id,
        cvid=910,
        title="Synthetic Hero",
        path="/tmp/comics/sh910",
    )
    async with db.read_session() as session:
        from sqlalchemy import select

        from foragerr.library.models import SeriesRow

        series_id = (
            await session.execute(
                select(SeriesRow.id).where(SeriesRow.cv_volume_id == 910)
            )
        ).scalar_one()
    keep = await _new_comic(db, source.id, "Synthetic Hero #1", machine_name="keep")
    withdrawn = await _new_comic(
        db, source.id, "Synthetic Hero #2", machine_name="withdrawn"
    )

    confident = ProposedMatch(
        best=MatchCandidate(
            kind="library",
            series_id=series_id,
            cv_volume_id=910,
            title="Synthetic Hero",
            year=2018,
            confidence=1.0,
        )
    )
    # The operator ignores one of them while the enrichment run is in flight.
    await review.ignore_entitlement(db, withdrawn)

    commands = FakeCommands()
    accepted = await _auto_accept(
        db,
        make_settings(config_dir),
        {keep: confident, withdrawn: confident},
        commands=commands,
        cv_configured=True,
    )

    assert accepted == 1
    assert (await repo.get_entitlement(db, keep)).review_status == "matched"
    after = await repo.get_entitlement(db, withdrawn)
    assert after.review_status == "ignored"
    assert after.matched_series_id is None
    assert {c[1]["entitlement_id"] for c in commands.grabs()} == {keep}


@pytest.mark.req("FRG-SRC-016")
async def test_auto_accept_skips_a_row_marked_non_comic_while_the_run_was_working(
    db, config_dir, root_folder_id, format_profile_id
):
    """The classification mark races the same window as an ignore, and the
    review-state check alone cannot see it: a marked row is still ``new``. A
    match landing on top of it would be worse than a lost mark — classification
    is review-time only, so the row would refuse every further mark with
    "already matched", stranding the correction the operator just made.
    """
    from foragerr.sources import review
    from foragerr.sources.enrich import _auto_accept
    from foragerr.sources.matching import MatchCandidate, ProposedMatch

    source = await _source(db, auto_sync=True)
    await _series(
        db,
        root_folder_id,
        format_profile_id,
        cvid=912,
        title="Synthetic Hero",
        path="/tmp/comics/sh912",
    )
    async with db.read_session() as session:
        from sqlalchemy import select

        from foragerr.library.models import SeriesRow

        series_id = (
            await session.execute(
                select(SeriesRow.id).where(SeriesRow.cv_volume_id == 912)
            )
        ).scalar_one()
    keep = await _new_comic(db, source.id, "Synthetic Hero #1", machine_name="keep")
    marked = await _new_comic(
        db, source.id, "Synthetic Sourcebook", machine_name="marked"
    )

    confident = ProposedMatch(
        best=MatchCandidate(
            kind="library",
            series_id=series_id,
            cv_volume_id=912,
            title="Synthetic Hero",
            year=2018,
            confidence=1.0,
        )
    )
    await review.classify_entitlement(db, marked, classification="other")

    commands = FakeCommands()
    accepted = await _auto_accept(
        db,
        make_settings(config_dir),
        {keep: confident, marked: confident},
        commands=commands,
        cv_configured=True,
    )

    assert accepted == 1
    after = await repo.get_entitlement(db, marked)
    assert after.review_status == "new"
    assert after.matched_series_id is None
    assert {c[1]["entitlement_id"] for c in commands.grabs()} == {keep}


@pytest.mark.req("FRG-SRC-011")
async def test_auto_accept_write_transaction_recheck_wins_the_toctou(
    db, config_dir, root_folder_id, format_profile_id, monkeypatch
):
    """The loop's pre-check re-read is itself a TOCTOU: a decision landing
    BETWEEN that read and the match write must still win: auto-sync passes
    ``require_new=True`` so the authoritative refusal happens inside the
    write transaction, not at the racy pre-check. Simulated by blinding the
    pre-check (it reports the stale ``new`` snapshot) while the row is in
    fact ignored: the write-side re-read refuses, the batch survives, and the
    operator's decision stands."""
    from foragerr.sources import enrich, review
    from foragerr.sources.enrich import _auto_accept
    from foragerr.sources.matching import MatchCandidate, ProposedMatch

    source = await _source(db, auto_sync=True)
    await _series(
        db,
        root_folder_id,
        format_profile_id,
        cvid=911,
        title="Synthetic Hero",
        path="/tmp/comics/sh911",
    )
    async with db.read_session() as session:
        from sqlalchemy import select

        from foragerr.library.models import SeriesRow

        series_id = (
            await session.execute(
                select(SeriesRow.id).where(SeriesRow.cv_volume_id == 911)
            )
        ).scalar_one()
    eid = await _new_comic(db, source.id, "Synthetic Hero #3", machine_name="raced")
    stale = await repo.get_entitlement(db, eid)  # pre-decision snapshot

    await review.ignore_entitlement(db, eid)

    async def _stale_read(_db, _eid):
        return stale  # the pre-check sees the world as it was before the ignore

    monkeypatch.setattr(enrich.repo, "get_entitlement", _stale_read)

    commands = FakeCommands()
    accepted = await _auto_accept(
        db,
        make_settings(config_dir),
        {
            eid: ProposedMatch(
                best=MatchCandidate(
                    kind="library",
                    series_id=series_id,
                    cv_volume_id=911,
                    title="Synthetic Hero",
                    year=2018,
                    confidence=1.0,
                )
            )
        },
        commands=commands,
        cv_configured=True,
    )

    monkeypatch.undo()
    assert accepted == 0
    after = await repo.get_entitlement(db, eid)
    assert after.review_status == "ignored"
    assert after.matched_series_id is None
    assert commands.grabs() == []


@pytest.mark.req("FRG-SRC-010")
async def test_the_marker_is_not_written_on_a_budget_hit(
    db, config_dir, root_folder_id, format_profile_id
):
    """The two states stay distinct end to end: the SAME entitlement gets NULL
    under a budget hit and the marker once ComicVine answers."""
    source = await _source(db)
    eid = await _new_comic(db, source.id, "Nobody is Guarding the Lighthouse Vol. 8")
    settings = make_settings(config_dir)

    await enrich_source(db, settings, source, cv_client=_budget_exhausted())
    assert (await repo.get_entitlement(db, eid)).proposed_match_json is None

    await enrich_source(
        db,
        settings,
        source,
        cv_client=_FakeCV(candidates=[_cand(1, "Distant Amber Signal", 2024)]),
    )
    stamped = json.loads((await repo.get_entitlement(db, eid)).proposed_match_json)
    assert stamped["verdict"] == VERDICT_NO_PLAUSIBLE_MATCH


@pytest.mark.req("FRG-SRC-010")
async def test_restore_recompute_replaces_a_marker_with_a_real_proposal(
    db, config_dir, root_folder_id, format_profile_id
):
    """The marker is not sticky against an operator action: restoring the row
    recomputes, and a library that has since grown yields a real proposal."""
    from foragerr.sources import review

    source = await _source(db)
    eid = await _new_comic(db, source.id, "Synthetic Hero #1")

    # Nothing to match yet → the marker.
    await enrich_source(
        db, make_settings(config_dir), source, cv_client=_FakeCV(candidates=[])
    )
    marked = await repo.get_entitlement(db, eid)
    assert json.loads(marked.proposed_match_json)["verdict"] == (
        VERDICT_NO_PLAUSIBLE_MATCH
    )

    # The operator adds the series, then ignores + restores the row.
    await _series(
        db,
        root_folder_id,
        format_profile_id,
        cvid=42,
        title="Synthetic Hero",
        path="/tmp/comics/sh",
    )
    await review.ignore_entitlement(db, eid)
    restored = await review.restore_entitlement(db, eid)

    assert restored.review_status == "new"
    payload = json.loads(restored.proposed_match_json)
    assert "verdict" not in payload  # the marker was replaced, not merged into
    assert payload["kind"] == "library"
    assert restored.proposed_series_id is not None
