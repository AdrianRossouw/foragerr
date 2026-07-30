"""The acquisition boundary inside the command handlers (FRG-SER-022).

The routes that normally start a search or a grab refuse a browse-only series,
but the commands behind them carry explicit ids and can be enqueued directly —
so the refusal has to hold on the WORKER side too, before any indexer request
and before any hand-off to a download client.

Every test here drives the registered handler and additionally makes the first
step past the boundary explode, so a missing guard fails as a bypass rather
than as a merely-different return value.
"""

from __future__ import annotations

import pytest

from foragerr.commands.registry import get_handler
from foragerr.library import repo
from foragerr.library.flows._common import SeriesSearchCommand
from foragerr.library.read_only import ReadOnlySeriesError
from foragerr.search_ops.commands import IssueSearchCommand, _handle_issue_search
from foragerr.search_ops.grab import GrabReleaseCommand
from http_support import make_settings
from indexers_support import make_factory  # noqa: F401 — fixture import
from .support import grab_rows, make_ctx, make_issue, make_series


@pytest.fixture
async def read_only_root_id(db, tmp_path) -> int:
    """A registered reference root: readable, never written, never acquired into."""
    root = tmp_path / "reference-library"
    root.mkdir()
    async with db.write_session() as session:
        row = await repo.create_root_folder(session, str(root), read_only=True)
        return row.id


@pytest.fixture
async def browse_only(db, format_profile_id, read_only_root_id) -> tuple[int, int]:
    """``(series_id, issue_id)`` for a fileless issue of a reference series."""
    series_id = await make_series(
        db,
        format_profile_id=format_profile_id,
        root_folder_id=read_only_root_id,
        title="Example Series",
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="1")
    return series_id, issue_id


@pytest.fixture
def no_search_side_effects(monkeypatch):
    """Explode on the first outbound search step past the boundary."""
    import foragerr.search_ops.commands as commands

    async def _explode(*args, **kwargs):
        raise AssertionError("search ran for a read-only series")

    monkeypatch.setattr(commands, "run_search", _explode)
    monkeypatch.setattr(commands, "_run_wanted_loop", _explode)


@pytest.fixture
def no_download_side_effects(monkeypatch):
    """Explode on the first grab step past the boundary (protocol resolution,
    which precedes the NZB fetch and ``client.download``)."""
    import foragerr.downloads.resolver as resolver

    async def _explode(*args, **kwargs):
        raise AssertionError("grab proceeded past the read-only boundary")

    monkeypatch.setattr(resolver, "protocol_for_grab", _explode)
    monkeypatch.setattr(resolver, "resolve_client_for", _explode)


def _assert_refusal(exc_info, series_id: int) -> None:
    message = str(exc_info.value)
    assert f"series {series_id}" in message
    assert "read-only reference library" in message


@pytest.mark.req("FRG-SER-022")
async def test_issue_search_command_refuses_a_read_only_series(
    db, browse_only, tmp_path, no_search_side_effects
):
    """The bypass F5 named: an ``issue-search`` enqueued with explicit ids."""
    series_id, issue_id = browse_only
    ctx = make_ctx(db, make_settings(tmp_path))

    with pytest.raises(ReadOnlySeriesError) as exc_info:
        await _handle_issue_search(
            IssueSearchCommand(series_id=series_id, issue_id=issue_id), ctx
        )

    _assert_refusal(exc_info, series_id)
    assert await grab_rows(db) == []


@pytest.mark.req("FRG-SER-022")
async def test_series_search_command_refuses_a_read_only_series(
    db, browse_only, tmp_path, no_search_side_effects
):
    """Refused, not reported as an empty walk: the selectables already exclude a
    browse-only series, so a zero-target summary would look like success."""
    series_id, _ = browse_only
    ctx = make_ctx(db, make_settings(tmp_path))

    with pytest.raises(ReadOnlySeriesError) as exc_info:
        await get_handler("series-search")(
            SeriesSearchCommand(series_id=series_id), ctx
        )

    _assert_refusal(exc_info, series_id)


@pytest.mark.req("FRG-SER-022")
async def test_series_search_all_scope_is_refused_too(
    db, browse_only, tmp_path, no_search_side_effects
):
    """``monitored_only=False`` widens the walk past the monitored flags, which
    is exactly the scope a browse-only series' unmonitored issues would fall
    into."""
    series_id, _ = browse_only
    ctx = make_ctx(db, make_settings(tmp_path))

    with pytest.raises(ReadOnlySeriesError):
        await get_handler("series-search")(
            SeriesSearchCommand(series_id=series_id, monitored_only=False), ctx
        )


def _handoff(**overrides) -> GrabReleaseCommand:
    payload = {
        "indexer_id": 1,
        "guid": "synthetic-guid-1",
        "link": "https://indexer.example.com/nzb/1",
        "title": "Example Series 001 (2024)",
    }
    payload.update(overrides)
    return GrabReleaseCommand(**payload)


@pytest.mark.req("FRG-SER-022")
async def test_grab_release_command_refuses_before_the_download_client(
    db, browse_only, tmp_path, no_download_side_effects
):
    """The other half of F5: a ``grab-release`` hand-off enqueued directly, which
    otherwise reaches ``client.download()`` without passing any route."""
    series_id, issue_id = browse_only
    ctx = make_ctx(db, make_settings(tmp_path))

    with pytest.raises(ReadOnlySeriesError) as exc_info:
        await get_handler("grab-release")(
            _handoff(series_id=series_id, issue_id=issue_id), ctx
        )

    _assert_refusal(exc_info, series_id)


@pytest.mark.req("FRG-SER-022")
async def test_grab_release_refuses_on_the_issue_identity_alone(
    db, browse_only, tmp_path, no_download_side_effects
):
    """A hand-crafted payload can name the issue and omit the series; either
    identity has to be enough to refuse."""
    _, issue_id = browse_only
    ctx = make_ctx(db, make_settings(tmp_path))

    with pytest.raises(ReadOnlySeriesError) as exc_info:
        await get_handler("grab-release")(_handoff(issue_id=issue_id), ctx)

    assert f"[{issue_id}]" in str(exc_info.value)


@pytest.mark.req("FRG-SER-022")
async def test_failed_download_does_not_re_enqueue_a_read_only_research(
    db, browse_only, tmp_path
):
    """The automatic post-failure re-search (FRG-DL-013) must not keep a refused
    acquisition alive: a browse-only issue is dropped from the re-search set
    instead of being enqueued once per failure cycle."""
    from foragerr.downloads.tracking import _enqueue_research, _FailureInfo

    series_id, issue_id = browse_only
    managed_series_id = await make_series(
        db,
        format_profile_id=await _profile_of(db, series_id),
        root_folder_id=await _managed_root(db, tmp_path),
        title="Managed Example Series",
    )
    managed_issue_id = await make_issue(db, series_id=managed_series_id)
    recorded: list[tuple] = []

    class _Commands:
        async def enqueue(self, name, payload=None, *, triggered_by="manual"):
            recorded.append((name, payload, triggered_by))

    await _enqueue_research(
        db,
        _Commands(),
        make_settings(tmp_path),
        [
            _FailureInfo(
                download_id="synthetic-download-1",
                issues=(
                    (series_id, issue_id),
                    (managed_series_id, managed_issue_id),
                ),
            )
        ],
    )

    assert [payload["issue_id"] for _, payload, _ in recorded] == [managed_issue_id]


async def _profile_of(db, series_id: int) -> int:
    from foragerr.library.models import SeriesRow

    async with db.read_session() as session:
        return (await session.get(SeriesRow, series_id)).format_profile_id


async def _managed_root(db, tmp_path) -> int:
    root = tmp_path / "managed-library"
    root.mkdir(exist_ok=True)
    async with db.write_session() as session:
        row = await repo.create_root_folder(session, str(root))
        return row.id
