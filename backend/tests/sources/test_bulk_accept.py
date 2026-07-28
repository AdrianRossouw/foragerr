"""Server-side bulk accept: each row applies its OWN proposal (FRG-SRC-011, D5).

The review screen's accept loop moves onto the server so a heterogeneous
selection — some rows proposing a library match, some proposing a ComicVine add
— resolves in ONE request, per-row transaction, per-row error. Same-title groups
converge through the existing FRG-SRC-008 sibling sweep rather than any new
apply-machinery: the first add creates the series, the sweep rewrites the
siblings' proposals, and each later row is re-read AT ITS TURN so it matches
instead of re-adding.
"""

from __future__ import annotations

import json

import pytest

from foragerr.db.base import utcnow
from foragerr.library.models import SeriesRow
from foragerr.sources import ratelimit, repo, review
from foragerr.sources.models import MATCHED_VIA_OPERATOR, SourceEntitlementRow
from flows_support import FakeCV, build_factory, flows_settings, reset_gate
from http_support import make_settings
from sources_support import (  # noqa: F401 — imported fixtures
    FakeCommands,
    _comic,
    _mk_series,
    _synced_source,
    format_profile_id,
    root_folder_id,
)


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    reset_gate()
    yield
    ratelimit.reset_gates()
    reset_gate()


def _cv_proposal(cvid: int, *, title: str = "Synthetic Hero") -> str:
    return json.dumps(
        {
            "kind": "comicvine",
            "series_id": None,
            "cv_volume_id": cvid,
            "title": title,
            "year": 2019,
            "confidence": 0.71,
            "auto": False,
            "candidates": [],
        },
        sort_keys=True,
    )


def _library_proposal(series_id: int, *, title: str = "Synthetic Hero") -> str:
    return json.dumps(
        {
            "kind": "library",
            "series_id": series_id,
            "cv_volume_id": None,
            "title": title,
            "year": 2019,
            "confidence": 0.93,
            "auto": False,
            "candidates": [],
        },
        sort_keys=True,
    )


async def _set_proposal(db, entitlement_id: int, payload: str | None) -> None:
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        row.proposed_match_json = payload
        row.proposed_series_id = None
        row.updated_at = utcnow()


# --- heterogeneous accept ---------------------------------------------------


@pytest.mark.req("FRG-SRC-011")
async def test_bulk_accept_applies_each_rows_own_proposal(
    db, config_dir, root_folder_id, format_profile_id
):
    """One request, two different targets: a library-kind row matches its own
    series and a ComicVine-kind row whose volume is already in the library
    resolves through the FRG-SRC-008 degrade. Neither is forced onto the
    other's target."""
    source = await _synced_source(db, config_dir)
    match_target = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7001, title="Synthetic Hero"
    )
    add_target = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7002, title="Other Hero"
    )
    row_a = await _comic(db, source.id, "synth_singleissue_01")
    row_b = await _comic(db, source.id, "synth_collected_edition_vol1")
    await _set_proposal(db, row_a.id, _library_proposal(match_target))
    await _set_proposal(db, row_b.id, _cv_proposal(7002))
    commands = FakeCommands()

    result = await review.bulk_accept(
        db,
        make_settings(config_dir),
        [row_a.id, row_b.id],
        commands=commands,
        matched_via=MATCHED_VIA_OPERATOR,
    )

    assert (result.applied, result.skipped, result.errors) == (2, 0, {})
    after_a = await repo.get_entitlement(db, row_a.id)
    after_b = await repo.get_entitlement(db, row_b.id)
    assert (after_a.review_status, after_a.matched_series_id) == (
        "matched",
        match_target,
    )
    assert (after_b.review_status, after_b.matched_series_id) == (
        "matched",
        add_target,
    )
    # Accept is an operator action end to end (FRG-PP-022 guard 3 / D7).
    assert after_a.matched_via == "operator"
    assert after_b.matched_via == "operator"
    # Accepting IS the download gate — each accepted row queued its own grab.
    assert {c[1]["entitlement_id"] for c in commands.grabs()} == {row_a.id, row_b.id}


@pytest.mark.req("FRG-SRC-011")
async def test_bulk_accept_falls_back_to_the_denormalized_proposed_series_id(
    db, config_dir, root_folder_id, format_profile_id
):
    """A row whose proposal JSON is unreadable but whose ``proposed_series_id``
    column is set still accepts as a match — the column is the fallback, not a
    dead end."""
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7010, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, ent.id)
        row.proposed_match_json = "not json at all"
        row.proposed_series_id = series_id

    result = await review.bulk_accept(
        db,
        make_settings(config_dir),
        [ent.id],
        commands=FakeCommands(),
        matched_via=MATCHED_VIA_OPERATOR,
    )
    assert result.applied == 1
    assert (await repo.get_entitlement(db, ent.id)).matched_series_id == series_id


# --- per-row error isolation ------------------------------------------------


@pytest.mark.req("FRG-SRC-011")
async def test_a_row_with_no_proposal_is_a_per_row_error_not_a_batch_failure(
    db, config_dir, root_folder_id, format_profile_id
):
    """An un-proposed row cannot be accepted (there is nothing to apply and
    borrowing a neighbour's target is precisely what this action forbids), but
    it must never veto the rest of the selection."""
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7020, title="Synthetic Hero"
    )
    good = await _comic(db, source.id, "synth_singleissue_01")
    bare = await _comic(db, source.id, "synth_collected_edition_vol1")
    await _set_proposal(db, good.id, _library_proposal(series_id))
    await _set_proposal(db, bare.id, None)

    result = await review.bulk_accept(
        db,
        make_settings(config_dir),
        [bare.id, good.id],
        commands=FakeCommands(),
        matched_via=MATCHED_VIA_OPERATOR,
    )

    assert result.applied == 1
    assert result.skipped == 1
    assert set(result.errors) == {bare.id}
    assert "no proposed match" in result.errors[bare.id]
    assert (await repo.get_entitlement(db, good.id)).review_status == "matched"
    assert (await repo.get_entitlement(db, bare.id)).review_status == "new"


@pytest.mark.req("FRG-SRC-011")
async def test_single_accept_of_an_unproposed_row_is_a_422(db, config_dir):
    """The per-row error above is the 422 the single-row action raises — the
    bulk wrapper reports it, it does not invent a different outcome."""
    source = await _synced_source(db, config_dir)
    ent = await _comic(db, source.id, "synth_singleissue_01")
    with pytest.raises(review.EntitlementActionError) as exc:
        await review.accept_entitlement(
            db,
            make_settings(config_dir),
            ent.id,
            commands=FakeCommands(),
            matched_via=MATCHED_VIA_OPERATOR,
        )
    assert exc.value.status == 422


@pytest.mark.req("FRG-SRC-011")
async def test_a_stale_proposal_target_errors_only_that_row(
    db, config_dir, root_folder_id, format_profile_id
):
    """A proposal pointing at a series that has since been deleted is that row's
    404; the neighbours still resolve."""
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7030, title="Synthetic Hero"
    )
    good = await _comic(db, source.id, "synth_singleissue_01")
    stale = await _comic(db, source.id, "synth_collected_edition_vol1")
    await _set_proposal(db, good.id, _library_proposal(series_id))
    await _set_proposal(db, stale.id, _library_proposal(999999))

    result = await review.bulk_accept(
        db,
        make_settings(config_dir),
        [good.id, stale.id],
        commands=FakeCommands(),
        matched_via=MATCHED_VIA_OPERATOR,
    )
    assert result.applied == 1
    assert set(result.errors) == {stale.id}
    assert (await repo.get_entitlement(db, good.id)).review_status == "matched"


# --- accept preconditions: only a row still in review (FRG-SRC-011) ---------


@pytest.mark.req("FRG-SRC-011")
async def test_bulk_accept_never_resurrects_an_ignored_row(
    db, config_dir, root_folder_id, format_profile_id
):
    """The verified regression: an ignored row inside an accept selection was
    flipped ignored → matched AND had its source-grab enqueued.

    Accept applies a row's PROPOSAL, and a proposal is the automatic matcher's
    suggestion for an undecided row — not a mandate over the operator's own
    withdrawal. A "select all in bundle" after a few ignores (or any stale
    selection) therefore silently re-downloaded exactly the items the operator
    had said no to. The ignore now survives as a per-row error, and the
    neighbouring row still resolves.
    """
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7040, title="Synthetic Hero"
    )
    good = await _comic(db, source.id, "synth_singleissue_01")
    withdrawn = await _comic(db, source.id, "synth_collected_edition_vol1")
    await _set_proposal(db, good.id, _library_proposal(series_id))
    await _set_proposal(db, withdrawn.id, _library_proposal(series_id))
    await review.ignore_entitlement(db, withdrawn.id)
    commands = FakeCommands()

    result = await review.bulk_accept(
        db,
        make_settings(config_dir),
        [withdrawn.id, good.id],
        commands=commands,
        matched_via=MATCHED_VIA_OPERATOR,
    )

    assert result.applied == 1
    assert set(result.errors) == {withdrawn.id}
    assert "ignored — restore it first" in result.errors[withdrawn.id]
    after = await repo.get_entitlement(db, withdrawn.id)
    assert after.review_status == "ignored"  # never resurrected
    assert after.matched_series_id is None
    assert after.download_state is None
    # ...and no grab was enqueued for it.
    assert {c[1]["entitlement_id"] for c in commands.grabs()} == {good.id}


@pytest.mark.req("FRG-SRC-011")
async def test_bulk_accept_refuses_an_already_matched_row(
    db, config_dir, root_folder_id, format_profile_id
):
    """The other half of the precondition: an already-resolved row is not
    re-decided by a bulk selection sweeping past it (and its ORIGINAL match
    target is preserved, not overwritten by whatever the stale proposal says)."""
    source = await _synced_source(db, config_dir)
    chosen = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7041, title="Synthetic Hero"
    )
    other = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7042, title="Other Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await _set_proposal(db, ent.id, _library_proposal(other))
    await review.match_entitlement(
        db, ent.id, series_id=chosen, commands=None,
        matched_via=MATCHED_VIA_OPERATOR,
    )

    result = await review.bulk_accept(
        db,
        make_settings(config_dir),
        [ent.id],
        commands=FakeCommands(),
        matched_via=MATCHED_VIA_OPERATOR,
    )

    assert result.applied == 0
    assert "already matched" in result.errors[ent.id]
    after = await repo.get_entitlement(db, ent.id)
    assert after.matched_series_id == chosen  # the operator's choice stands


@pytest.mark.req("FRG-SRC-011")
async def test_single_accept_of_an_ignored_row_is_a_409(
    db, config_dir, root_folder_id, format_profile_id
):
    """The per-row error above is the single-row action's 409."""
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7043, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await _set_proposal(db, ent.id, _library_proposal(series_id))
    await review.ignore_entitlement(db, ent.id)
    with pytest.raises(review.EntitlementActionError) as exc:
        await review.accept_entitlement(
            db,
            make_settings(config_dir),
            ent.id,
            commands=FakeCommands(),
            matched_via=MATCHED_VIA_OPERATOR,
        )
    assert exc.value.status == 409


@pytest.mark.req("FRG-SRC-011")
async def test_the_accept_precondition_is_re_read_inside_the_write_transaction(
    db, config_dir, root_folder_id, format_profile_id
):
    """The pre-check alone is a TOCTOU: accept validates in one session and
    ``match_entitlement`` writes in another, so an ignore committing in between
    would still land on a ``matched`` row. ``require_new`` re-reads under the
    writer lock; calling the write path directly with it proves that is where
    the guard bites, not merely in the caller."""
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7044, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await review.ignore_entitlement(db, ent.id)
    commands = FakeCommands()

    with pytest.raises(review.EntitlementActionError) as exc:
        await review.match_entitlement(
            db,
            ent.id,
            series_id=series_id,
            commands=commands,
            matched_via=MATCHED_VIA_OPERATOR,
            require_new=True,
        )
    assert exc.value.status == 409
    assert (await repo.get_entitlement(db, ent.id)).review_status == "ignored"
    assert commands.grabs() == []

    # The OPERATOR's explicit match is unaffected — re-deciding a withdrawn row
    # is a legitimate action, and that is the action they took.
    await review.match_entitlement(
        db, ent.id, series_id=series_id, commands=commands,
        matched_via=MATCHED_VIA_OPERATOR,
    )
    assert (await repo.get_entitlement(db, ent.id)).review_status == "matched"


@pytest.mark.req("FRG-SRC-010")
async def test_a_no_plausible_match_marker_is_never_accepted_via_a_stale_column(
    db, config_dir, root_folder_id, format_profile_id
):
    """A verdict marker is authoritative: "we looked, there is nothing".

    The denormalized ``proposed_series_id`` column is only the fallback for an
    ABSENT or unparseable proposal. Reading it for a marker row — whose whole
    point is that the automatic matcher found nothing — resurrected whatever
    series the column happened to still hold and accepted the row against it.
    """
    source = await _synced_source(db, config_dir)
    stale_series = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7045, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    marker = json.dumps(
        {
            "verdict": "no-plausible-match",
            "universe": "comicvine",
            "candidates": [],
            "auto": False,
        },
        sort_keys=True,
    )
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, ent.id)
        row.proposed_match_json = marker
        row.proposed_series_id = stale_series  # the stale denormalized column
        row.updated_at = utcnow()

    with pytest.raises(review.EntitlementActionError) as exc:
        await review.accept_entitlement(
            db,
            make_settings(config_dir),
            ent.id,
            commands=FakeCommands(),
            matched_via=MATCHED_VIA_OPERATOR,
        )
    assert exc.value.status == 422
    assert "no proposed match" in str(exc.value)
    assert (await repo.get_entitlement(db, ent.id)).review_status == "new"


# --- same-volume group convergence (FRG-SRC-008 sweep) ----------------------


@pytest.mark.req("FRG-SRC-011")
async def test_same_volume_group_converges_through_one_add(
    db, config_dir, root_folder_id, format_profile_id
):
    """Bulk-accepting a collapsed group whose rows ALL propose the same
    not-yet-in-library volume: the first row adds the series, the sweep
    re-resolves its siblings, and — because each row's proposal is re-read at
    its own turn — the rest match into that one series. No "already in the
    library" error, exactly one series created."""
    source = await _synced_source(db, config_dir)
    settings = flows_settings(config_dir)
    factory = build_factory(
        settings, FakeCV().volume(7100, name="Synthetic Hero").handler()
    )
    comics = await repo.list_entitlements(db, source.id, classification="comic")
    assert len(comics) >= 3
    ids = [e.id for e in comics]
    for eid in ids:
        await _set_proposal(db, eid, _cv_proposal(7100))
    commands = FakeCommands()

    result = await review.bulk_accept(
        db,
        settings,
        ids,
        commands=commands,
        factory=factory,
        root_folder_id=root_folder_id,
        matched_via=MATCHED_VIA_OPERATOR,
    )

    assert (result.applied, result.errors) == (len(ids), {})
    rows = [await repo.get_entitlement(db, eid) for eid in ids]
    assert {r.review_status for r in rows} == {"matched"}
    targets = {r.matched_series_id for r in rows}
    assert len(targets) == 1  # one series, not one per row
    async with db.read_session() as session:
        from sqlalchemy import select

        created = (
            (
                await session.execute(
                    select(SeriesRow).where(SeriesRow.cv_volume_id == 7100)
                )
            )
            .scalars()
            .all()
        )
    assert len(created) == 1
    assert created[0].id == targets.pop()


@pytest.mark.req("FRG-SRC-011")
async def test_accept_reads_the_proposal_at_its_turn_not_from_a_snapshot(
    db, config_dir, root_folder_id, format_profile_id
):
    """The convergence above depends on re-reading: a sibling whose proposal was
    a ComicVine ADD when the request arrived must act on the LIBRARY match the
    sweep left it. Proven without ComicVine at all — the sibling's stored
    proposal is rewritten mid-run by the acting row's degrade, and a snapshot
    accept would have tried (and failed) to add."""
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7200, title="Synthetic Hero"
    )
    acting = await _comic(db, source.id, "synth_singleissue_01")
    sibling = await _comic(db, source.id, "synth_collected_edition_vol1")
    for eid in (acting.id, sibling.id):
        await _set_proposal(db, eid, _cv_proposal(7200))

    # No factory and no ComicVine key: a genuine add would blow up, so both rows
    # can only resolve via the degrade + sweep.
    result = await review.bulk_accept(
        db,
        make_settings(config_dir),
        [acting.id, sibling.id],
        commands=FakeCommands(),
        matched_via=MATCHED_VIA_OPERATOR,
    )
    assert (result.applied, result.errors) == (2, {})
    after = await repo.get_entitlement(db, sibling.id)
    assert after.matched_series_id == series_id
    assert after.matched_via == "operator"


# --- provenance is fail-closed (D7) ------------------------------------------


@pytest.mark.req("FRG-SRC-004")
async def test_accept_requires_an_explicit_matched_via(db, config_dir):
    """The whole point of D7: a caller that forgets the provenance keyword fails
    loudly instead of silently minting operator provenance."""
    source = await _synced_source(db, config_dir)
    ent = await _comic(db, source.id, "synth_singleissue_01")
    with pytest.raises(TypeError):
        await review.accept_entitlement(
            db, make_settings(config_dir), ent.id, commands=None
        )
