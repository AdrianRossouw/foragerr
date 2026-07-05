"""Review-gate regression tests for the search pipeline + commands (change 4).

- C9  (FRG-SRCH-014): the grab hand-off / release cache stamps the DECISION's
  own mapped identity, so a re-search under a different issue converges on the
  same identity rather than overwriting the (indexer, guid) row with the
  searched issue.
- C6  (FRG-NFR-010): one indexer row whose settings fail to load is isolated —
  the healthy indexer's search still completes and the bad row is reported.
- C7  (FRG-NFR-005): an indexer whose search raises an unexpected error is
  attributed a failure and escalated on the back-off ladder; the batch survives.
- C15 (FRG-SRCH-008): a settings-less handler context fails fast with a clear
  RuntimeError instead of an AttributeError deep in the factory.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from foragerr.commands.service import HandlerContext, daemon_offload
from foragerr.indexers.caps import CapsCache
from foragerr.indexers.models import IndexerRow
from foragerr.providers.backoff import PROVIDER_INDEXER, ProviderBackoff
from foragerr.search_ops import cache_decisions, get_cached, run_search
from foragerr.search_ops.commands import _build_infra
from http_support import make_settings
from indexers_support import make_factory  # noqa: F401
from .support import feed_handler, make_indexer, make_issue, make_series


async def _run(db, tmp_path, handler, *, series_id, issue_id):
    factory, _ = make_factory(tmp_path, handler)
    return await run_search(
        db=db,
        settings=make_settings(tmp_path),
        factory=factory,
        backoff=ProviderBackoff(db),
        caps_cache=CapsCache(),
        series_id=series_id,
        issue_id=issue_id,
        path="auto",
        min_interval=0.0,
    )


@pytest.mark.req("FRG-SRCH-014")
async def test_grab_carries_decision_mapped_identity_across_re_search(
    db, format_profile_id, root_folder_id
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    id7 = await make_issue(db, series_id=series_id, issue_number="7")
    id8 = await make_issue(db, series_id=series_id, issue_number="8")
    await make_indexer(db)

    # The SAME guid release (maps to issue #7) is returned for every query.
    handler = feed_handler("Saga 007 (2012)", guid_prefix="same")

    # Search issue A (#7): the release is approved and mapped to #7.
    result_a = await _run(
        db, db.db_path.parent, handler, series_id=series_id, issue_id=id7
    )
    assert result_a is not None and result_a.approved
    grab = result_a.approved[0]
    guid = grab.candidate.guid
    await cache_decisions(db, id7, result_a.decisions)

    # Re-search issue B (#8): the same guid is returned but maps to #7, so it is
    # rejected for #8 — caching it must NOT overwrite the row with issue #8.
    result_b = await _run(
        db, db.db_path.parent, handler, series_id=series_id, issue_id=id8
    )
    assert result_b is not None
    await cache_decisions(db, id8, result_b.decisions)

    # The cached hand-off carries the release's true identity (#7), not the
    # last searched issue (#8) — the (indexer, guid) key stays sound.
    handoff = await get_cached(db, grab.candidate.indexer_id, guid)
    assert handoff is not None
    assert handoff.issue_id == id7
    assert handoff.series_id == series_id


@pytest.mark.req("FRG-NFR-010")
async def test_one_corrupt_indexer_row_does_not_abort_the_search(
    db, format_profile_id, root_folder_id
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")
    healthy_id = await make_indexer(db, name="Healthy", priority=10)
    corrupt_id = await make_indexer(db, name="Corrupt", priority=20)

    # Corrupt the second row's settings JSON so it cannot load.
    async with db.write_session() as session:
        row = await session.get(IndexerRow, corrupt_id)
        row.settings = "{not valid json"

    result = await _run(
        db, db.db_path.parent, feed_handler("Saga 007 (2012)"),
        series_id=series_id, issue_id=issue_id,
    )
    assert result is not None
    # The healthy indexer's release is decided...
    assert result.approved
    # ...and the corrupt row is surfaced as a failed outcome, never searched.
    by_id = {o.indexer_id: o for o in result.indexer_outcomes}
    assert by_id[corrupt_id].failure is not None
    assert by_id[healthy_id].failure is None


@pytest.mark.req("FRG-NFR-005")
async def test_crashing_indexer_is_isolated_and_escalated(
    db, format_profile_id, root_folder_id, monkeypatch
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")
    indexer_id = await make_indexer(db)

    import foragerr.search_ops.pipeline as pipeline

    async def _boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(pipeline, "search_indexer", _boom)

    backoff = ProviderBackoff(db)
    factory, _ = make_factory(db.db_path.parent, feed_handler("Saga 007 (2012)"))
    result = await run_search(
        db=db,
        settings=make_settings(db.db_path.parent),
        factory=factory,
        backoff=backoff,
        caps_cache=CapsCache(),
        series_id=series_id,
        issue_id=issue_id,
        path="auto",
        min_interval=0.0,
    )
    assert result is not None
    [outcome] = result.indexer_outcomes
    assert outcome.failure is not None
    assert "RuntimeError" in str(outcome.failure)
    # The provider was escalated on the back-off ladder.
    status = await backoff.status(PROVIDER_INDEXER, indexer_id)
    assert status.active and status.level >= 1


@pytest.mark.req("FRG-SRCH-008")
def test_settingsless_context_raises_clear_error(db):
    ctx = HandlerContext(
        db=db, bus=None, settings=None, offload=daemon_offload
    )
    with pytest.raises(RuntimeError, match="settings-bearing CommandService"):
        _build_infra(ctx)
