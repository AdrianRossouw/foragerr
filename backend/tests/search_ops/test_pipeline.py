"""The shared search pipeline: fan-out, decide, dedup, order (FRG-SRCH-008).

Also covers the global usenet-retention config field reaching the indexer
search as ``maxage`` (FRG-IDX-009, the deferred global-retention slice).
"""

from __future__ import annotations

import pytest

from foragerr.indexers.caps import CapsCache
from foragerr.providers.backoff import ProviderBackoff
from foragerr.search import DecisionOutcome
from foragerr.search_ops import run_search
from http_support import make_settings
from indexers_support import (  # noqa: F401 (_reset_indexer_gates autouse in conftest)
    make_factory,
)
from .support import feed_handler, make_indexer, make_issue, make_series


async def _run(db, tmp_path, handler, *, series_id, issue_id, path, **settings_kw):
    factory, transport = make_factory(tmp_path, handler)
    result = await run_search(
        db=db,
        settings=make_settings(tmp_path, **settings_kw),
        factory=factory,
        backoff=ProviderBackoff(db),
        caps_cache=CapsCache(),
        series_id=series_id,
        issue_id=issue_id,
        path=path,
        min_interval=0.0,
    )
    return result, transport


@pytest.mark.req("FRG-SRCH-008")
async def test_run_search_approves_and_orders_best_first(
    db, format_profile_id, root_folder_id
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")
    await make_indexer(db, priority=10)

    handler = feed_handler("Saga 007 (2012)")
    result, _ = await _run(
        db, tmp_path=db.db_path.parent, handler=handler,
        series_id=series_id, issue_id=issue_id, path="auto",
    )
    assert result is not None
    assert result.approved, "the correctly-mapped release should be approved"
    best = result.approved[0]
    assert best.mapped_series_id == series_id
    assert best.mapped_issue_id == issue_id
    # approved rows sort before rejected ones (comparator order).
    assert result.decisions[0].approved


@pytest.mark.req("FRG-SRCH-008")
async def test_wrong_series_release_is_rejected_not_grabbed(
    db, format_profile_id, root_folder_id
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id,
        title="Saga",
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")
    await make_indexer(db)

    # A decodable release for a DIFFERENT series comes back from the q= search.
    handler = feed_handler("Batman 007 (2012)")
    result, _ = await _run(
        db, tmp_path=db.db_path.parent, handler=handler,
        series_id=series_id, issue_id=issue_id, path="auto",
    )
    assert result is not None
    assert not result.approved
    assert result.decisions, "the rejected release is still returned with reasons"
    assert result.decisions[0].outcome is not DecisionOutcome.APPROVED
    assert result.decisions[0].reasons  # carries a visible rejection reason


@pytest.mark.req("FRG-SRCH-008")
async def test_unknown_format_release_is_approved_pre_download(
    db, format_profile_id, root_folder_id
):
    """The engine permits unknown container formats pre-download (release titles
    rarely name their container), so a titled-but-formatless release approves."""
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")
    await make_indexer(db)

    handler = feed_handler("Saga 007 (2012)")  # no cbz/cbr/pdf token
    result, _ = await _run(
        db, tmp_path=db.db_path.parent, handler=handler,
        series_id=series_id, issue_id=issue_id, path="auto",
    )
    assert result.approved


@pytest.mark.req("FRG-IDX-009")
async def test_global_usenet_retention_reaches_indexer_as_maxage(
    db, format_profile_id, root_folder_id
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")
    await make_indexer(db)

    handler = feed_handler("Saga 007 (2012)")
    _, transport = await _run(
        db, tmp_path=db.db_path.parent, handler=handler,
        series_id=series_id, issue_id=issue_id, path="auto",
        usenet_retention_days=3000,
    )
    search_reqs = [r for r in transport.requests if r.url.params.get("t") == "search"]
    assert search_reqs
    assert all(r.url.params.get("maxage") == "3000" for r in search_reqs)


@pytest.mark.req("FRG-SRCH-014")
async def test_interactive_path_skips_non_interactive_indexers(
    db, format_profile_id, root_folder_id
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")
    await make_indexer(db, enable_interactive=False, enable_auto=True)

    handler = feed_handler("Saga 007 (2012)")
    result, transport = await _run(
        db, tmp_path=db.db_path.parent, handler=handler,
        series_id=series_id, issue_id=issue_id, path="interactive",
    )
    assert result is not None
    assert result.decisions == []
    assert transport.requests == []  # the interactive-disabled indexer is not queried
