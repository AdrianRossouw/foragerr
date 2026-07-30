"""Store entitlements never acquire into a read-only series (FRG-SER-022).

Accepting an entitlement IS the download gate, so every action that can accept
one — match, accept, bulk match, apply-to-group, retry — has to refuse a
browse-only target, and the worker has to refuse again when it runs: a queued
grab outlives the request that queued it, and the entitlement can be re-matched
while the download is in flight.
"""

from __future__ import annotations

import httpx
import pytest

from foragerr.library import repo as library_repo
from foragerr.library.read_only import ReadOnlySeriesError
from foragerr.sources import ratelimit, repo, review
from foragerr.sources.models import MATCHED_VIA_OPERATOR, SourceEntitlementRow
from http_support import make_settings
from sources_support import (  # noqa: F401 — imported fixtures
    FakeCommands,
    _comic,
    _mk_series,
    _synced_source,
    format_profile_id,
    make_factory,
    root_folder_id,
)


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


@pytest.fixture
async def read_only_root_id(db, tmp_path) -> int:
    root = tmp_path / "reference-library"
    root.mkdir()
    async with db.write_session() as session:
        row = await library_repo.create_root_folder(session, str(root), read_only=True)
        return row.id


@pytest.fixture
async def browse_only_series_id(db, read_only_root_id, format_profile_id) -> int:
    return await _mk_series(
        db,
        read_only_root_id,
        format_profile_id,
        cvid=901,
        title="Example Reference Series",
    )


async def _proposal(db, entitlement_id: int, series_id: int) -> None:
    """Stamp a library-kind proposal so ``accept`` has something to apply."""
    import json

    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        row.proposed_series_id = series_id
        row.proposed_match_json = json.dumps(
            {"kind": "library", "series_id": series_id, "title": "Example Series"},
            sort_keys=True,
        )


async def _row(db, entitlement_id: int) -> SourceEntitlementRow:
    return await repo.get_entitlement(db, entitlement_id)


@pytest.mark.req("FRG-SER-022")
async def test_match_refuses_and_leaves_the_row_undecided(
    db, config_dir, browse_only_series_id
):
    """The refusal is inside the transaction that would stamp ``matched``, so
    the row is not left matched-but-never-grabbable."""
    source = await _synced_source(db, config_dir)
    ent = await _comic(db, source.id, "synth_singleissue_01")
    commands = FakeCommands()

    with pytest.raises(ReadOnlySeriesError):
        await review.match_entitlement(
            db,
            ent.id,
            series_id=browse_only_series_id,
            commands=commands,
            matched_via=MATCHED_VIA_OPERATOR,
        )

    after = await _row(db, ent.id)
    assert after.review_status == "new"
    assert after.matched_series_id is None
    assert after.download_state is None
    assert commands.enqueued == []


@pytest.mark.req("FRG-SER-022")
async def test_accept_refuses_when_the_proposal_names_a_read_only_series(
    db, config_dir, browse_only_series_id
):
    source = await _synced_source(db, config_dir)
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await _proposal(db, ent.id, browse_only_series_id)
    commands = FakeCommands()

    with pytest.raises(ReadOnlySeriesError):
        await review.accept_entitlement(
            db,
            make_settings(config_dir),
            ent.id,
            commands=commands,
            matched_via=MATCHED_VIA_OPERATOR,
        )

    assert (await _row(db, ent.id)).review_status == "new"
    assert commands.enqueued == []


@pytest.mark.req("FRG-SER-022")
async def test_bulk_match_refuses_the_whole_selection(
    db, config_dir, browse_only_series_id
):
    """All-or-none: nothing is matched and nothing is queued, rather than a
    per-row error repeated for every member of the selection."""
    source = await _synced_source(db, config_dir)
    first = await _comic(db, source.id, "synth_singleissue_01")
    second = await _comic(db, source.id, "synth_collected_edition_vol1")
    commands = FakeCommands()

    with pytest.raises(ReadOnlySeriesError):
        await review.bulk_match(
            db,
            [first.id, second.id],
            series_id=browse_only_series_id,
            commands=commands,
            matched_via=MATCHED_VIA_OPERATOR,
        )

    for eid in (first.id, second.id):
        assert (await _row(db, eid)).review_status == "new"
    assert commands.enqueued == []


@pytest.mark.req("FRG-SER-022")
async def test_bulk_accept_refuses_before_applying_any_row(
    db, config_dir, browse_only_series_id, root_folder_id, format_profile_id
):
    """One browse-only proposal in the batch refuses the request with nothing
    applied — the heterogeneous rows make a mid-batch refusal a partial one."""
    source = await _synced_source(db, config_dir)
    managed_series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=902, title="Example Series"
    )
    managed = await _comic(db, source.id, "synth_singleissue_01")
    browse_only = await _comic(db, source.id, "synth_collected_edition_vol1")
    await _proposal(db, managed.id, managed_series_id)
    await _proposal(db, browse_only.id, browse_only_series_id)
    commands = FakeCommands()

    with pytest.raises(ReadOnlySeriesError):
        await review.bulk_accept(
            db,
            make_settings(config_dir),
            [managed.id, browse_only.id],
            commands=commands,
            matched_via=MATCHED_VIA_OPERATOR,
        )

    assert (await _row(db, managed.id)).review_status == "new"
    assert commands.enqueued == []


@pytest.mark.req("FRG-SER-022")
async def test_apply_to_group_refuses_a_read_only_pick(
    db, config_dir, browse_only_series_id
):
    source = await _synced_source(db, config_dir)
    ent = await _comic(db, source.id, "synth_singleissue_01")
    commands = FakeCommands()

    with pytest.raises(ReadOnlySeriesError):
        await review.bulk_apply_to_group(
            db,
            make_settings(config_dir),
            [ent.id],
            series_id=browse_only_series_id,
            commands=commands,
            matched_via=MATCHED_VIA_OPERATOR,
        )

    assert (await _row(db, ent.id)).review_status == "new"
    assert commands.enqueued == []


@pytest.mark.req("FRG-SER-022")
async def test_add_refuses_a_read_only_destination_root(
    db, config_dir, read_only_root_id
):
    """Registering a reference library is legitimate; adding a store purchase
    INTO one is not, and the refusal precedes the add + refresh + scan chain."""
    source = await _synced_source(db, config_dir)
    ent = await _comic(db, source.id, "synth_singleissue_01")
    commands = FakeCommands()

    with pytest.raises(ReadOnlySeriesError):
        await review.add_entitlement(
            db,
            make_settings(config_dir),
            ent.id,
            commands=commands,
            root_folder_id=read_only_root_id,
            cv_volume_id=90210,
            matched_via=MATCHED_VIA_OPERATOR,
        )

    assert (await _row(db, ent.id)).review_status == "new"
    assert commands.enqueued == []


@pytest.mark.req("FRG-SER-022")
async def test_queue_grab_seam_refuses_even_for_an_already_matched_row(
    db, config_dir, browse_only_series_id
):
    """The shared accept seam is the last line of defence: a row that reached
    ``matched`` by any route still never gets a queued state or a grab."""
    source = await _synced_source(db, config_dir)
    ent = await _comic(db, source.id, "synth_singleissue_01")
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, ent.id)
        row.review_status = "matched"
        row.matched_series_id = browse_only_series_id
    commands = FakeCommands()

    with pytest.raises(ReadOnlySeriesError):
        await review._queue_grab(db, ent.id, commands)

    assert (await _row(db, ent.id)).download_state is None
    assert commands.enqueued == []


@pytest.mark.req("FRG-SER-022")
async def test_retry_refuses_and_keeps_the_failed_row_intact(
    db, config_dir, browse_only_series_id
):
    source = await _synced_source(db, config_dir)
    ent = await _comic(db, source.id, "synth_singleissue_01")
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, ent.id)
        row.review_status = "matched"
        row.matched_series_id = browse_only_series_id
        row.download_state = "failed"
        row.download_error = "synthetic prior failure"
    commands = FakeCommands()

    with pytest.raises(ReadOnlySeriesError):
        await review.retry_download(db, ent.id, commands=commands)

    after = await _row(db, ent.id)
    assert after.download_state == "failed"
    assert after.download_error == "synthetic prior failure"
    assert commands.enqueued == []


@pytest.mark.req("FRG-SER-022")
async def test_run_grab_refuses_before_fetching_a_single_byte(
    db, config_dir, browse_only_series_id
):
    """The worker-side re-check: a queued grab outlives its request, so the
    boundary is tested again before the signed-URL fetch. The refusal also
    lands on the entitlement's own failed surface, so the operator sees why."""
    from foragerr.sources.grab import run_grab

    source = await _synced_source(db, config_dir)
    ent = await _comic(db, source.id, "synth_singleissue_01")
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, ent.id)
        row.review_status = "matched"
        row.matched_series_id = browse_only_series_id
        row.download_state = "queued"

    def _explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the store was contacted for a read-only series")

    factory = make_factory(config_dir, httpx.MockTransport(_explode))

    with pytest.raises(ReadOnlySeriesError):
        await run_grab(
            db, factory, make_settings(config_dir), ent.id, min_interval=0.0
        )

    after = await _row(db, ent.id)
    assert after.download_state == "failed"
    assert "read-only reference library" in after.download_error
