"""Review-first entitlement workflow (FRG-SRC-004): match/add/ignore/restore
(single + bulk), accept-gates-download, decision survival across re-sync, and
the auto-sync toggle (default OFF; opt-in accepts only confident matches).
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from foragerr.sources import ratelimit, repo, review
from foragerr.sources.enrich import enrich_source
from foragerr.sources.models import MATCHED_VIA_OPERATOR
from foragerr.sources.service import run_sync
from http_support import make_settings
from sources_support import (  # noqa: F401 — imported fixtures
    FakeCommands,
    GAMEKEY,
    _comic,
    _mk_series,
    _synced_source,
    fixture_bytes,
    format_profile_id,
    make_factory,
    order_handler,
    root_folder_id,
)


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


# --- match + accept-gates-download ------------------------------------------


@pytest.mark.req("FRG-SRC-004")
async def test_match_links_series_and_queues_grab(
    db, config_dir, root_folder_id, format_profile_id
):
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=555, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    commands = FakeCommands()

    row = await review.match_entitlement(
        db, ent.id, series_id=series_id, commands=commands,
        matched_via=MATCHED_VIA_OPERATOR,
    )
    assert row.review_status == "matched"
    assert row.matched_series_id == series_id
    # The match is stamped operator-made (FRG-PP-022 guard 3) — the import
    # pipeline's ordinal fallback only trusts a human-chosen series.
    assert row.matched_via == "operator"
    # Accept queues the grab (the accept action IS the download gate).
    assert row.download_state == "queued"
    assert commands.enqueued == [
        ("source-grab", {"entitlement_id": ent.id}, "accept")
    ]


@pytest.mark.req("FRG-SRC-004")
async def test_default_sync_downloads_nothing(db, config_dir):
    """No download or library mutation on a default (auto_sync OFF) source."""
    source = await _synced_source(db, config_dir, auto_sync=False)
    commands = FakeCommands()
    settings = make_settings(config_dir)

    summary = await enrich_source(
        db, settings, source, commands=commands, cv_client=None
    )
    assert "auto_sync=off" in summary
    # Nothing accepted, nothing queued, every comic still awaiting review.
    assert commands.enqueued == []
    comics = await repo.list_entitlements(db, source.id, classification="comic")
    assert all(e.review_status == "new" for e in comics)
    assert all(e.download_state is None for e in comics)


@pytest.mark.req("FRG-SRC-004")
async def test_match_to_nonexistent_series_is_rejected(db, config_dir):
    """A match naming a phantom series id is a 404, never a phantom link."""
    source = await _synced_source(db, config_dir)
    ent = await _comic(db, source.id, "synth_singleissue_01")
    with pytest.raises(review.EntitlementActionError) as exc:
        await review.match_entitlement(
            db,
            ent.id,
            series_id=999999,
            commands=None,
            matched_via=MATCHED_VIA_OPERATOR,
        )
    assert exc.value.status == 404
    after = await repo.get_entitlement(db, ent.id)
    assert after.review_status == "new"
    assert after.matched_series_id is None


@pytest.mark.req("FRG-SRC-004")
async def test_double_accept_enqueues_one_grab(
    db, config_dir, root_folder_id, format_profile_id
):
    """Re-accepting an already-queued entitlement is idempotent — one grab only."""
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=571, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    commands = FakeCommands()

    await review.match_entitlement(
        db, ent.id, series_id=series_id, commands=commands,
        matched_via=MATCHED_VIA_OPERATOR,
    )
    await review.match_entitlement(
        db, ent.id, series_id=series_id, commands=commands,
        matched_via=MATCHED_VIA_OPERATOR,
    )
    # The second accept finds download_state already "queued" → no second grab.
    assert commands.enqueued == [
        ("source-grab", {"entitlement_id": ent.id}, "accept")
    ]


@pytest.mark.req("FRG-SRC-004")
async def test_ignore_after_accept_clears_download_axis(
    db, config_dir, root_folder_id, format_profile_id
):
    """Ignoring a queued entitlement cancels the grab by clearing download_state,
    so the in-flight run_grab aborts at its re-read guard (FRG-SRC-004/006)."""
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=572, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await review.match_entitlement(
        db, ent.id, series_id=series_id, commands=None,
        matched_via=MATCHED_VIA_OPERATOR,
    )
    queued = await repo.get_entitlement(db, ent.id)
    assert queued.download_state == "queued"

    ignored = await review.ignore_entitlement(db, ent.id)
    assert ignored.review_status == "ignored"
    assert ignored.download_state is None  # grab cancelled on the download axis


# --- ignore + restore -------------------------------------------------------


@pytest.mark.req("FRG-SRC-004")
async def test_ignore_then_restore_recomputes_proposal(
    db, config_dir, root_folder_id, format_profile_id
):
    source = await _synced_source(db, config_dir)
    await _mk_series(
        db, root_folder_id, format_profile_id, cvid=556, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")

    ignored = await review.ignore_entitlement(db, ent.id)
    assert ignored.review_status == "ignored"

    restored = await review.restore_entitlement(db, ent.id)
    assert restored.review_status == "new"
    assert restored.matched_series_id is None
    # The match provenance goes with the dropped match (FRG-PP-022 guard 3).
    assert restored.matched_via is None
    # Restore recomputes the proposed match (library-first) — a confident one.
    assert restored.proposed_series_id is not None
    assert restored.proposed_match_json is not None


@pytest.mark.req("FRG-SRC-004")
async def test_restore_acts_only_on_an_ignored_row(
    db, config_dir, root_folder_id, format_profile_id
):
    """Restore is the inverse of ignore, and destructive to everything else: it
    clears ``matched_series_id`` / ``matched_via`` and overwrites the proposal.

    A mixed bulk restore — the natural result of "select all" over a filtered
    list — therefore stripped matched rows of their match on the way past. Both
    non-ignored states are per-row errors now and nothing is written.
    """
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=5601, title="Synthetic Hero"
    )
    matched = await _comic(db, source.id, "synth_singleissue_01")
    await review.match_entitlement(
        db, matched.id, series_id=series_id, commands=None,
        matched_via=MATCHED_VIA_OPERATOR,
    )
    fresh = await _comic(db, source.id, "synth_collected_edition_vol1")

    for eid, state in ((matched.id, "matched"), (fresh.id, "new")):
        with pytest.raises(review.EntitlementActionError) as exc:
            await review.restore_entitlement(db, eid)
        assert exc.value.status == 409
        assert state in str(exc.value)

    after = await repo.get_entitlement(db, matched.id)
    assert after.review_status == "matched"
    assert after.matched_series_id == series_id
    assert after.matched_via == "operator"


@pytest.mark.req("FRG-SRC-004")
async def test_bulk_restore_reports_non_ignored_rows_without_touching_them(
    db, config_dir, root_folder_id, format_profile_id
):
    """A selection spanning review buckets restores the ignored rows and leaves
    the rest exactly as they were, reported per row."""
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=5602, title="Synthetic Hero"
    )
    ignored = await _comic(db, source.id, "synth_singleissue_01")
    matched = await _comic(db, source.id, "synth_collected_edition_vol1")
    await review.ignore_entitlement(db, ignored.id)
    await review.match_entitlement(
        db, matched.id, series_id=series_id, commands=None,
        matched_via=MATCHED_VIA_OPERATOR,
    )

    result = await review.bulk_restore(db, [ignored.id, matched.id])

    assert result.applied == 1
    assert set(result.errors) == {matched.id}
    assert (await repo.get_entitlement(db, ignored.id)).review_status == "new"
    survivor = await repo.get_entitlement(db, matched.id)
    assert (survivor.review_status, survivor.matched_series_id) == (
        "matched",
        series_id,
    )


@pytest.mark.req("FRG-SRC-004")
async def test_bulk_restore_defers_proposals_and_single_restore_does_not(
    db, config_dir, root_folder_id, format_profile_id
):
    """A bulk restore must not serialize a rate-limited catalog call per row.

    The calls are spaced by ``comicvine_min_interval_seconds``, so N of them
    held the operator for N × the spacing while the action committed row by
    row — a refresh mid-flight showed a partial result. Bulk therefore parks
    the rows back to ``new`` un-proposed (the deferral shape FRG-META-016
    sanctions) and the enrichment pass fills them in; the single-row restore,
    which is one call the operator is watching, still recomputes inline.
    """
    from types import SimpleNamespace

    from foragerr.sources.enrich import eligible_for_enrichment

    class _CountingCV:
        def __init__(self):
            self.calls = 0

        async def suggest_series(self, term):
            self.calls += 1
            return SimpleNamespace(
                candidates=[
                    SimpleNamespace(
                        cv_volume_id=5610, name="Synthetic Hero", start_year=2018
                    )
                ]
            )

    source = await _synced_source(db, config_dir)
    await _mk_series(
        db, root_folder_id, format_profile_id, cvid=5610, title="Synthetic Hero"
    )
    cv = _CountingCV()
    comics = await repo.list_entitlements(db, source.id, classification="comic")
    ids = [e.id for e in comics]
    assert len(ids) > 1
    # Give every row a standing proposal, so the deferral is proven to CLEAR
    # one rather than merely to leave an already-empty column empty.
    for eid in ids:
        await review.ignore_entitlement(db, eid)
        await review.restore_entitlement(db, eid, cv_client=cv, cv_configured=True)
    assert cv.calls == len(ids)
    for eid in ids:
        await review.ignore_entitlement(db, eid)

    result = await review.bulk_restore(db, ids)

    assert result.applied == len(ids)
    assert cv.calls == len(ids)  # not one more: bulk consults no catalog at all
    for eid in ids:
        row = await repo.get_entitlement(db, eid)
        assert row.review_status == "new"
        assert row.proposed_match_json is None
        assert row.proposed_series_id is None
        # NULL is what puts the row in front of the enrichment pass.
        assert eligible_for_enrichment(row, cv_configured=True)

    # The single-row form is unchanged: it still pays for its own proposal.
    await review.ignore_entitlement(db, ids[0])
    single = await review.restore_entitlement(
        db, ids[0], cv_client=cv, cv_configured=True
    )
    assert cv.calls == len(ids) + 1
    assert single.proposed_match_json is not None


@pytest.mark.req("FRG-SRC-004")
async def test_bulk_restore_of_a_non_comic_row_leaves_its_proposal_alone(
    db, config_dir
):
    """The non-comic carve-out (FRG-SRC-016) is about which COLUMNS move, and
    the deferral does not widen it: a row the operator never asked the catalog
    about keeps whatever it had, rather than being nulled into the enrichment
    pass's queue."""
    source = await _synced_source(db, config_dir)
    others = await repo.list_entitlements(db, source.id, classification="other")
    assert others
    row = others[0]
    before = row.proposed_match_json
    await review.ignore_entitlement(db, row.id)

    result = await review.bulk_restore(db, [row.id])

    assert result.applied == 1
    after = await repo.get_entitlement(db, row.id)
    assert after.review_status == "new"
    assert after.proposed_match_json == before


@pytest.mark.req("FRG-SRC-010")
async def test_restore_consults_comicvine_and_records_the_catalog_universe(
    db, config_dir, root_folder_id, format_profile_id
):
    """Restore is operator-initiated and single-row, so it affords the one CV
    call — and needs it: recomputing library-only stamped a
    ``library-fallback`` proposal (with ``auto: true``!) that the review screen
    renders as a catalog verdict and that freezes the row out of the next
    enrichment pass."""
    import json
    from types import SimpleNamespace

    class _FakeCV:
        def __init__(self):
            self.calls = 0

        async def suggest_series(self, term):
            self.calls += 1
            return SimpleNamespace(
                candidates=[
                    SimpleNamespace(
                        cv_volume_id=5603, name="Synthetic Hero", start_year=2018
                    )
                ]
            )

    source = await _synced_source(db, config_dir)
    await _mk_series(
        db, root_folder_id, format_profile_id, cvid=5603, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await review.ignore_entitlement(db, ent.id)

    cv = _FakeCV()
    restored = await review.restore_entitlement(
        db, ent.id, cv_client=cv, cv_configured=True
    )

    assert cv.calls == 1  # exactly one, not one per candidate
    payload = json.loads(restored.proposed_match_json)
    assert payload["universe"] == "comicvine"


@pytest.mark.req("FRG-SRC-010")
async def test_restore_leaves_the_row_retryable_when_the_budget_is_exhausted(
    db, config_dir, root_folder_id, format_profile_id
):
    """Budget exhaustion is a DEFERRAL, not a verdict (FRG-META-016): the row
    returns to ``new`` un-proposed so the next enrichment pass recomputes it. It
    must never fall back to a library-only guess and never stamp a marker —
    either would freeze the row with the CV lookup permanently skipped."""
    from foragerr.metadata.errors import ComicVineBudgetExhausted

    class _BudgetCV:
        async def suggest_series(self, term):
            raise ComicVineBudgetExhausted("volume", retry_after_seconds=60)

    source = await _synced_source(db, config_dir)
    # A library series that WOULD have produced a confident fallback proposal.
    await _mk_series(
        db, root_folder_id, format_profile_id, cvid=5604, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await review.ignore_entitlement(db, ent.id)

    restored = await review.restore_entitlement(
        db, ent.id, cv_client=_BudgetCV(), cv_configured=True
    )

    assert restored.review_status == "new"
    assert restored.proposed_match_json is None
    assert restored.proposed_series_id is None


@pytest.mark.req("FRG-SRC-010")
async def test_restore_never_persists_a_library_fallback_on_a_keyed_deployment(
    db, config_dir, root_folder_id, format_profile_id
):
    """The belt to the brace above. On a ComicVine-configured deployment a
    ``library-fallback`` universe can only mean a CV call that should have
    happened did not, so it is left un-proposed and retryable rather than
    written out as a catalog verdict."""
    source = await _synced_source(db, config_dir)
    await _mk_series(
        db, root_folder_id, format_profile_id, cvid=5605, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await review.ignore_entitlement(db, ent.id)

    restored = await review.restore_entitlement(
        db, ent.id, cv_client=None, cv_configured=True
    )
    assert restored.review_status == "new"
    assert restored.proposed_match_json is None

    # The genuinely UNCONFIGURED deployment still gets its honest fallback.
    await review.ignore_entitlement(db, ent.id)
    honest = await review.restore_entitlement(db, ent.id, cv_configured=False)
    assert '"universe": "library-fallback"' in honest.proposed_match_json


# --- decision survives a re-sync (idempotency) ------------------------------


@pytest.mark.req("FRG-SRC-004")
async def test_operator_decision_survives_resync(
    db, config_dir, root_folder_id, format_profile_id
):
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=557, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await review.match_entitlement(
        db, ent.id, series_id=series_id, commands=None,
        matched_via=MATCHED_VIA_OPERATOR,
    )
    ignored = await _comic(db, source.id, "synth_collected_edition_vol1")
    await review.ignore_entitlement(db, ignored.id)

    # Re-sync: the diff refreshes display fields but must preserve decisions.
    handler = order_handler(
        list_body=b'[{"gamekey":"%s"}]' % GAMEKEY.encode(),
        order_bodies={GAMEKEY: fixture_bytes("order_comics.json")},
    )
    factory = make_factory(config_dir, httpx.MockTransport(handler))
    await run_sync(db, factory, source, min_interval=0.0)

    after_match = await repo.get_entitlement(db, ent.id)
    after_ignore = await repo.get_entitlement(db, ignored.id)
    assert after_match.review_status == "matched"
    assert after_match.matched_series_id == series_id
    assert after_ignore.review_status == "ignored"


# --- bulk -------------------------------------------------------------------


@pytest.mark.req("FRG-SRC-004")
async def test_bulk_ignore_then_bulk_restore(db, config_dir):
    source = await _synced_source(db, config_dir)
    comics = await repo.list_entitlements(db, source.id, classification="comic")
    ids = [e.id for e in comics]

    result = await review.bulk_ignore(db, ids)
    assert result.applied == len(ids)
    statuses = [(await repo.get_entitlement(db, i)).review_status for i in ids]
    assert statuses == ["ignored"] * len(ids)

    restored = await review.bulk_restore(db, ids)
    assert restored.applied == len(ids)
    statuses = [(await repo.get_entitlement(db, i)).review_status for i in ids]
    assert statuses == ["new"] * len(ids)


# --- auto-sync (opt-in) -----------------------------------------------------


@pytest.mark.req("FRG-SRC-004")
async def test_auto_sync_accepts_only_confident_matches(
    db, config_dir, root_folder_id, format_profile_id
):
    source = await _synced_source(db, config_dir, auto_sync=True)
    await _mk_series(
        db, root_folder_id, format_profile_id, cvid=558, title="Synthetic Hero"
    )
    commands = FakeCommands()
    settings = make_settings(config_dir)

    summary = await enrich_source(
        db, settings, source, commands=commands, cv_client=None
    )
    assert "auto_sync=on" in summary

    # The single issue confidently matches "Synthetic Hero" → auto-accepted +
    # grab queued; the collected edition scores below threshold → stays new.
    single = await _comic(db, source.id, "synth_singleissue_01")
    collected = await _comic(db, source.id, "synth_collected_edition_vol1")
    assert single.review_status == "matched"
    # Auto-sync's acceptance is stamped as such (FRG-PP-022 guard 3): no human
    # chose this series, so the import pipeline withholds the ordinal fallback.
    assert single.matched_via == "auto"
    assert single.download_state == "queued"
    assert collected.review_status == "new"
    assert collected.download_state is None
    assert commands.enqueued == [
        ("source-grab", {"entitlement_id": single.id}, "accept")
    ]


# --- ignore-mid-import race: cancel the pending completed-download row -------


@pytest.mark.req("FRG-SRC-004")
async def test_ignore_cancels_pending_import_row(
    db, config_dir, root_folder_id, format_profile_id
):
    """Ignoring after the grab handed off to import deletes the unclaimed
    ``humble:{id}`` tracked row, so the drain never imports the ignored item
    (and the handoff's download-id dedup can re-create it on restore+re-accept).
    """
    from pathlib import Path

    from foragerr.downloads.models import TrackedDownloadRow
    from foragerr.downloads.state import TrackedDownloadState
    from foragerr.sources.grab import _handoff_to_import

    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=555, title="Synthetic Hero"
    )
    ent = await review.match_entitlement(
        db,
        (await _comic(db, source.id, "synth_singleissue_01")).id,
        series_id=series_id,
        commands=FakeCommands(),
        matched_via=MATCHED_VIA_OPERATOR,
    )
    # The grab's real import handoff: a humble:{id} row in import_pending.
    await _handoff_to_import(db, ent, Path("/tmp/staging/x/file.cbz"))
    async with db.read_session() as session:
        row = (
            await session.execute(
                select(TrackedDownloadRow).where(
                    TrackedDownloadRow.download_id == f"humble:{ent.id}"
                )
            )
        ).scalar_one()
    assert row.state == TrackedDownloadState.IMPORT_PENDING.value

    await review.ignore_entitlement(db, ent.id)

    async with db.read_session() as session:
        remaining = (
            (
                await session.execute(
                    select(TrackedDownloadRow).where(
                        TrackedDownloadRow.download_id == f"humble:{ent.id}"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert remaining == []  # the unclaimed completed download is cancelled
    fresh = await repo.get_entitlement(db, ent.id)
    assert fresh.review_status == "ignored"
    assert fresh.download_state is None


@pytest.mark.req("FRG-SRC-004")
async def test_ignore_leaves_claimed_import_row_to_the_hook_guard(
    db, config_dir, root_folder_id, format_profile_id
):
    """A row the drain has already claimed (``importing``) is NOT deleted by
    ignore — and when that claimed import reaches its terminal transition, the
    import hook's ``review_status`` re-read guard discards its entitlement
    effects (no ownership claim, no axis resurrection)."""
    import datetime as dt

    from foragerr.db.base import utcnow
    from foragerr.downloads.models import TrackedDownloadRow
    from foragerr.downloads.state import TRACKED_STATUS_OK, TrackedDownloadState
    from foragerr.sources.import_hook import apply_source_import

    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=556, title="Synthetic Hero"
    )
    ent = await review.match_entitlement(
        db,
        (await _comic(db, source.id, "synth_singleissue_01")).id,
        series_id=series_id,
        commands=FakeCommands(),
        matched_via=MATCHED_VIA_OPERATOR,
    )
    now = utcnow()
    async with db.write_session() as session:
        session.add(
            TrackedDownloadRow(
                download_id=f"humble:{ent.id}",
                client_id=None,
                client_name="Humble Bundle",
                protocol="humble",
                source="store",
                state=TrackedDownloadState.IMPORTING.value,
                status=TRACKED_STATUS_OK,
                series_id=series_id,
                issue_id=None,
                title=ent.human_name,
                output_path="/tmp/staging/x",
                encrypted=False,
                added_at=now,
                updated_at=now,
            )
        )

    await review.ignore_entitlement(db, ent.id)

    async with db.read_session() as session:
        row = (
            await session.execute(
                select(TrackedDownloadRow).where(
                    TrackedDownloadRow.download_id == f"humble:{ent.id}"
                )
            )
        ).scalar_one()
    assert row.state == TrackedDownloadState.IMPORTING.value

    # The claimed import's terminal transition is discarded by the hook guard:
    # no ownership claim, no download-axis resurrection.
    async with db.write_session() as session:
        await apply_source_import(
            session,
            download_id=f"humble:{ent.id}",
            final_state=TrackedDownloadState.IMPORTED,
            imported_issues=[],
            now=dt.datetime(2026, 7, 12, 12, 0, 0),
        )
    fresh = await repo.get_entitlement(db, ent.id)
    assert fresh.review_status == "ignored"
    assert fresh.download_state is None


@pytest.mark.req("FRG-SRC-004")
async def test_ignore_deletes_dead_terminal_rows_so_reaccept_can_rehandoff(
    db, config_dir, root_folder_id, format_profile_id
):
    """Ignore deletes a ``failed_pending`` (or any non-``importing``) humble row:
    the grab handoff dedups on download_id regardless of state, so a surviving
    dead terminal would silently strand restore + re-accept with no claimable
    row — the entitlement would sit in import_pending forever."""
    from pathlib import Path

    from foragerr.db.base import utcnow
    from foragerr.downloads.models import TrackedDownloadRow
    from foragerr.downloads.state import TRACKED_STATUS_ERROR, TrackedDownloadState
    from foragerr.sources.grab import _handoff_to_import

    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=557, title="Synthetic Hero"
    )
    ent = await review.match_entitlement(
        db,
        (await _comic(db, source.id, "synth_singleissue_01")).id,
        series_id=series_id,
        commands=FakeCommands(),
        matched_via=MATCHED_VIA_OPERATOR,
    )
    now = utcnow()
    async with db.write_session() as session:
        session.add(
            TrackedDownloadRow(
                download_id=f"humble:{ent.id}",
                client_id=None,
                client_name="Humble Bundle",
                protocol="humble",
                source="store",
                state=TrackedDownloadState.FAILED_PENDING.value,
                status=TRACKED_STATUS_ERROR,
                series_id=series_id,
                issue_id=None,
                title=ent.human_name,
                output_path="/tmp/staging/x",
                encrypted=False,
                added_at=now,
                updated_at=now,
            )
        )

    await review.ignore_entitlement(db, ent.id)

    async with db.read_session() as session:
        remaining = (
            (
                await session.execute(
                    select(TrackedDownloadRow).where(
                        TrackedDownloadRow.download_id == f"humble:{ent.id}"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert remaining == []

    # Restore + re-accept can hand off afresh: the dedup finds no stale row.
    restored = await review.restore_entitlement(db, ent.id)
    assert restored.review_status == "new"
    rematched = await review.match_entitlement(
        db, ent.id, series_id=series_id, commands=FakeCommands(),
        matched_via=MATCHED_VIA_OPERATOR,
    )
    await _handoff_to_import(db, rematched, Path("/tmp/staging/x/file.cbz"))
    async with db.read_session() as session:
        row = (
            await session.execute(
                select(TrackedDownloadRow).where(
                    TrackedDownloadRow.download_id == f"humble:{ent.id}"
                )
            )
        ).scalar_one()
    assert row.state == TrackedDownloadState.IMPORT_PENDING.value


# --- matched_via is fail-closed (design D7) ---------------------------------


@pytest.mark.req("FRG-SRC-004")
async def test_the_review_chain_refuses_an_unstamped_match(db, config_dir):
    """``matched_via`` used to DEFAULT to operator, so a caller that simply
    forgot it minted operator provenance silently — and operator provenance is
    what unlocks the import pipeline's ordinal fallback (FRG-PP-022 guard 3).
    Every entry point now requires the keyword, so the omission is a TypeError
    at call time instead of a wrong stamp in the database."""
    source = await _synced_source(db, config_dir)
    ent = await _comic(db, source.id, "synth_singleissue_01")

    with pytest.raises(TypeError):
        await review.match_entitlement(db, ent.id, series_id=1, commands=None)
    with pytest.raises(TypeError):
        await review.add_entitlement(
            db, make_settings(config_dir), ent.id, cv_volume_id=1
        )
    with pytest.raises(TypeError):
        await review.bulk_match(db, [ent.id], series_id=1)

    # Nothing was written by any of the refused calls.
    after = await repo.get_entitlement(db, ent.id)
    assert (after.review_status, after.matched_via) == ("new", None)


@pytest.mark.req("FRG-SRC-004")
async def test_auto_accept_remains_the_only_automatic_provenance_writer(
    db, config_dir, root_folder_id, format_profile_id
):
    """The fail-closed sweep must not have changed WHICH caller writes what:
    auto-sync still stamps ``auto``, and a subsequent human re-match on the same
    row stamps ``operator`` — the two provenances remain distinguishable."""
    source = await _synced_source(db, config_dir, auto_sync=True)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7400, title="Synthetic Hero"
    )
    await enrich_source(
        db, make_settings(config_dir), source, commands=FakeCommands(), cv_client=None
    )
    single = await _comic(db, source.id, "synth_singleissue_01")
    assert single.matched_via == "auto"

    rematched = await review.match_entitlement(
        db,
        single.id,
        series_id=series_id,
        commands=FakeCommands(),
        matched_via=MATCHED_VIA_OPERATOR,
    )
    assert rematched.matched_via == "operator"
