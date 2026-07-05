"""Automatic search commands: issue + series search (FRG-SRCH-008).

Drives the command handlers directly over a real migrated DB, with the
pipeline's outbound factory routed at a stub Newznab feed. Asserts the grab
hand-off is recorded (an enqueued, inert ``grab-release`` command) and that the
live series-search handler replaces the change-3 inert stub.
"""

from __future__ import annotations

import json

import pytest

from foragerr.commands.registry import get_handler
from foragerr.search_ops.commands import (
    IssueSearchCommand,
    SeriesSearchCommand,
    _handle_issue_search,
)
from http_support import make_settings
from indexers_support import make_factory  # noqa: F401
from .support import (
    feed_handler,
    grab_rows,
    make_ctx,
    make_indexer,
    make_issue,
    make_series,
    patch_pipeline_factory,
)


@pytest.fixture(autouse=True)
def _fast_interval(monkeypatch):
    """Drop the per-indexer 2 s spacing gate so command runs stay snappy."""
    import foragerr.search_ops.commands as commands

    monkeypatch.setattr(commands, "MIN_INTERVAL", 0.0)


@pytest.mark.req("FRG-SRCH-008")
async def test_issue_search_records_grab_for_best_approved(
    db, format_profile_id, root_folder_id, monkeypatch, tmp_path
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")
    indexer_id = await make_indexer(db)

    patch_pipeline_factory(monkeypatch, tmp_path, feed_handler("Saga 007 (2012)"))
    ctx = make_ctx(db, make_settings(tmp_path))
    summary = await _handle_issue_search(
        IssueSearchCommand(series_id=series_id, issue_id=issue_id), ctx
    )

    rows = await grab_rows(db)
    assert len(rows) == 1, "one grab hand-off recorded for the best approved release"
    payload = json.loads(rows[0].payload)
    assert payload["indexer_id"] == indexer_id
    assert payload["series_id"] == series_id
    assert payload["issue_id"] == issue_id
    assert payload["link"] and payload["guid"]
    assert "grab recorded" in summary
    # The grab hand-off runs on the download pool (change-5 seam), not search.
    assert rows[0].workload_class == "download"


@pytest.mark.req("FRG-SRCH-008")
async def test_issue_search_no_approved_release_records_no_grab(
    db, format_profile_id, root_folder_id, monkeypatch, tmp_path
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")
    await make_indexer(db)

    # Only a wrong-series release comes back -> nothing approved.
    patch_pipeline_factory(monkeypatch, tmp_path, feed_handler("Batman 007 (2012)"))
    ctx = make_ctx(db, make_settings(tmp_path))
    summary = await _handle_issue_search(
        IssueSearchCommand(series_id=series_id, issue_id=issue_id), ctx
    )
    assert await grab_rows(db) == []
    assert "no approved release" in summary


@pytest.mark.req("FRG-SRCH-008")
async def test_series_search_covers_each_wanted_issue(
    db, format_profile_id, root_folder_id, monkeypatch, tmp_path
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    id7 = await make_issue(db, series_id=series_id, issue_number="7")
    id8 = await make_issue(db, series_id=series_id, issue_number="8")
    # An issue that already has a file is NOT wanted -> not searched/grabbed.
    await make_issue(db, series_id=series_id, issue_number="9", with_file="/x/9.cbz")
    await make_indexer(db)

    # The feed returns both wanted issues' releases for any query; the per-issue
    # search-match spec keeps only the release matching the searched issue.
    handler = feed_handler("Saga 007 (2012)", "Saga 008 (2012)")
    patch_pipeline_factory(monkeypatch, tmp_path, handler)
    ctx = make_ctx(db, make_settings(tmp_path))
    summary = await get_handler("series-search")(
        SeriesSearchCommand(series_id=series_id), ctx
    )

    rows = await grab_rows(db)
    grabbed_issue_ids = {json.loads(r.payload)["issue_id"] for r in rows}
    assert grabbed_issue_ids == {id7, id8}
    assert "2 wanted issue(s)" in summary


@pytest.mark.req("FRG-SRCH-008")
async def test_grab_handoff_is_live_in_change_5(
    db, format_profile_id, root_folder_id, tmp_path
):
    """The grab hand-off is now LIVE (change 5, FRG-DL-006): it resolves the
    protocol-matched download client instead of recording an inert string. With
    no download client configured, a grab fails typed + retryable (never a silent
    drop), proving the handler is no longer inert."""
    from foragerr.downloads.errors import NoDownloadClientError
    from foragerr.search_ops.grab import GrabReleaseCommand

    indexer_id = await make_indexer(db)  # so the release protocol resolves
    ctx = make_ctx(db, make_settings(tmp_path))
    with pytest.raises(NoDownloadClientError):
        await get_handler("grab-release")(
            GrabReleaseCommand(
                indexer_id=indexer_id,
                guid="g-1",
                link="https://idx.test/nzb/1",
                title="Saga 007",
            ),
            ctx,
        )


@pytest.mark.req("FRG-SRCH-008")
async def test_series_search_replaces_the_change3_inert_stub(
    db, format_profile_id, root_folder_id, monkeypatch, tmp_path
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    await make_indexer(db)
    patch_pipeline_factory(monkeypatch, tmp_path, feed_handler())
    ctx = make_ctx(db, make_settings(tmp_path))

    summary = await get_handler("series-search")(
        SeriesSearchCommand(series_id=series_id), ctx
    )
    # The live handler summarizes a real search, never the inert stub's string.
    assert "deferred" not in summary
    assert "searched" in summary
