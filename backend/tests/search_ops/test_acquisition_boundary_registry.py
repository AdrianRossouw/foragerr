"""Registry-level invariant for the acquisition boundary (FRG-SER-022).

Guarding acquisition per endpoint has been shown to leak: the command backbone
accepts any registered command name with an explicit payload, so a handler that
starts an acquisition without consulting the boundary is reachable whatever its
routes do. This module therefore asserts the property over the REGISTRY rather
than over a list of endpoints:

1. every command the production app registers is classified — a new command
   fails this file until someone decides which side of the boundary it is on;
2. every command classified as targeted acquisition has a case here, and its
   handler refuses a browse-only target while the first step past the boundary
   is rigged to explode.

The one acquiring command with no handler guard (``backlog-search``) is held to
a different, also checkable property: its payload cannot name a target at all,
so its scope comes from selectables that exclude read-only series.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from foragerr.commands.registry import BaseCommand, command_names, command_type, get_handler
from foragerr.library import repo
from foragerr.library.flows._common import SeriesSearchCommand
from foragerr.library.read_only import ReadOnlySeriesError
from foragerr.search_ops.commands import BacklogSearchCommand, IssueSearchCommand
from foragerr.search_ops.grab import GrabReleaseCommand
from foragerr.sources.grab import SourceGrabCommand
from foragerr.sources.models import SourceEntitlementRow, SourceRow
from http_support import make_settings
from indexers_support import make_factory  # noqa: F401 — fixture import
from .support import make_ctx, make_issue, make_series

#: Commands that can START an acquisition for a target their payload names, so
#: the handler itself must consult the read-only boundary (FRG-SER-022).
_TARGETED_ACQUISITION = {
    "issue-search",
    "series-search",
    "grab-release",
    "source-grab",
}

#: Every other command the app registers, with the reason it is not a targeted
#: acquisition. Written out so that adding a command is a decision, not an
#: omission; file-mutating commands answer to the write boundary instead
#: (FRG-SER-021), which has its own coverage.
_NOT_TARGETED_ACQUISITION = {
    "backlog-search": "acquires, but its payload names no target (see below)",
    "backup-database": "writes only the configuration directory",
    "convert-issue": "file mutation, not acquisition",
    "convert-series": "file mutation, not acquisition",
    "creator-bibliography-fetch": "metadata read",
    "creators-backfill": "metadata read",
    "delete-series-files": "file mutation, not acquisition",
    "housekeeping": "retention pruning of own tables",
    "library-import": "file mutation, not acquisition",
    "library-import-scan": "reads the filesystem to propose an import",
    "manual-import": "file mutation, not acquisition",
    "noop": "test command with no effect",
    "process-ddl-queue": "drains downloads an already-guarded grab enqueued",
    "process-imports": "file mutation, not acquisition",
    "prune-release-cache": "retention pruning of own tables",
    "prune-sessions": "retention pruning of own tables",
    "pull-refresh": "fetches the pull list; targets no series",
    "refresh-series": "metadata read",
    "rename-series": "file mutation, not acquisition",
    "rescan-series": "file mutation, not acquisition",
    "scan-series": "file mutation, not acquisition",
    "source-recompute-proposals": "recomputes proposals; downloads nothing",
    "source-sync": "reads store inventory; downloads nothing",
    "track-downloads": "observes clients; its re-search hand-off is filtered",
}


@pytest.fixture
def registered_commands(tmp_path: Path) -> set[str]:
    """The command names the PRODUCTION app registers.

    Built by constructing the app (registration happens on the imports inside
    ``create_app``) rather than by importing a hand-kept list, so a command
    registered by a new area is visible here without anyone remembering to add
    it. Names whose command class lives outside the ``foragerr`` package are
    test-registered and excluded."""
    from foragerr.app import create_app

    create_app(make_settings(tmp_path / "app-config"))
    return {
        name
        for name in command_names()
        if command_type(name).__module__.startswith("foragerr.")
    }


@pytest.fixture
async def browse_only_target(db, format_profile_id, tmp_path) -> dict:
    """A reference-root series, one of its issues, and an entitlement matched to
    it — the three shapes a targeted acquisition command can name."""
    root = tmp_path / "reference-library"
    root.mkdir()
    async with db.write_session() as session:
        root_row = await repo.create_root_folder(session, str(root), read_only=True)
        root_id = root_row.id
    series_id = await make_series(
        db,
        format_profile_id=format_profile_id,
        root_folder_id=root_id,
        title="Example Series",
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="1")
    now = dt.datetime(2026, 1, 1, 12, 0, 0)
    async with db.write_session() as session:
        source = SourceRow(
            type="humble",
            name="Example Store",
            settings="{}",
            connection_state="connected",
            auto_sync=False,
            added_at=now,
        )
        session.add(source)
        await session.flush()
        entitlement = SourceEntitlementRow(
            source_id=source.id,
            gamekey="synthetic-gamekey",
            machine_name="example_series_01",
            human_name="Example Series #1",
            classification="comic",
            review_status="matched",
            matched_series_id=series_id,
            md5="0" * 32,
            filename="example-series-001.cbz",
            file_size=1024,
            formats_json="[]",
            created_at=now,
            updated_at=now,
        )
        session.add(entitlement)
        await session.flush()
        entitlement_id = entitlement.id
    return {
        "series_id": series_id,
        "issue_id": issue_id,
        "entitlement_id": entitlement_id,
    }


def _command_for(name: str, target: dict) -> BaseCommand:
    """The registry-shaped payload naming a browse-only target for ``name``."""
    if name == "issue-search":
        return IssueSearchCommand(
            series_id=target["series_id"], issue_id=target["issue_id"]
        )
    if name == "series-search":
        return SeriesSearchCommand(series_id=target["series_id"])
    if name == "grab-release":
        return GrabReleaseCommand(
            indexer_id=1,
            guid="synthetic-guid-1",
            link="https://indexer.example.com/nzb/1",
            title="Example Series 001 (2024)",
            series_id=target["series_id"],
            issue_id=target["issue_id"],
        )
    if name == "source-grab":
        return SourceGrabCommand(entitlement_id=target["entitlement_id"])
    raise AssertionError(
        f"{name!r} is classified as targeted acquisition but has no case here"
    )


@pytest.fixture
def nothing_may_be_acquired(monkeypatch):
    """Rig every first step past the boundary to explode: the indexer search,
    the download-client resolution, the store CDN stream, and the store API
    client. A handler that skips its guard fails as a bypass."""
    import foragerr.downloads.resolver as resolver
    import foragerr.search_ops.commands as search_commands
    import foragerr.sources.grab as source_grab

    async def _explode(*args, **kwargs):
        raise AssertionError("acquisition proceeded past the read-only boundary")

    def _explode_sync(*args, **kwargs):
        raise AssertionError("acquisition proceeded past the read-only boundary")

    monkeypatch.setattr(search_commands, "run_search", _explode)
    monkeypatch.setattr(search_commands, "_run_wanted_loop", _explode)
    monkeypatch.setattr(resolver, "protocol_for_grab", _explode)
    monkeypatch.setattr(resolver, "resolve_client_for", _explode)
    monkeypatch.setattr(source_grab.dl, "download_link", _explode)
    monkeypatch.setattr(source_grab, "HumbleClient", _explode_sync)


@pytest.mark.req("FRG-SER-022")
def test_every_registered_command_is_classified(registered_commands):
    """The invariant that makes the rest of this file complete: an unclassified
    command means nobody decided whether it can acquire."""
    classified = _TARGETED_ACQUISITION | set(_NOT_TARGETED_ACQUISITION)
    assert registered_commands - classified == set(), (
        "classify the new command as targeted acquisition (and add a case in "
        "_command_for) or record why it is not"
    )
    assert classified - registered_commands == set(), (
        "a classified command is no longer registered"
    )
    assert not (_TARGETED_ACQUISITION & set(_NOT_TARGETED_ACQUISITION))


@pytest.mark.req("FRG-SER-022")
@pytest.mark.parametrize("name", sorted(_TARGETED_ACQUISITION))
async def test_targeted_acquisition_handler_refuses_a_read_only_target(
    name, db, browse_only_target, tmp_path, nothing_may_be_acquired
):
    """Each acquiring handler refuses on its own, independently of the route
    that enqueued it."""
    ctx = make_ctx(db, make_settings(tmp_path))

    with pytest.raises(ReadOnlySeriesError) as exc_info:
        await get_handler(name)(_command_for(name, browse_only_target), ctx)

    assert "read-only reference library" in str(exc_info.value)


@pytest.mark.req("FRG-SER-022")
def test_the_unguarded_acquiring_command_cannot_name_a_target():
    """``backlog-search`` is exempt from a handler guard only because it cannot
    be pointed at anything — its scope is the wanted selectable, which excludes
    read-only series. Growing a target field breaks that exemption."""
    payload_fields = set(BacklogSearchCommand.model_fields) - {"name"}
    assert payload_fields == set()
    assert "backlog-search" in _NOT_TARGETED_ACQUISITION
