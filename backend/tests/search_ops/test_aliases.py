"""User-editable series aliases drive release mapping (FRG-SRCH-003).

The alias store is the area-3 deferred slice: persistence + edit path + the
context builder that folds aliases into the engine's matching keys. These tests
pin the load-bearing scenario — a release that matches a series ONLY through an
alias maps to it — plus the edit path that maintains the aliases.
"""

from __future__ import annotations

import json

import pytest

from foragerr.indexers.caps import CapsCache
from foragerr.library import repo
from foragerr.library.flows import decode_aliases, edit_series
from foragerr.providers.backoff import ProviderBackoff
from foragerr.search_ops import run_search
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


@pytest.mark.req("FRG-SRCH-003")
async def test_release_maps_to_series_only_via_alias(
    db, format_profile_id, root_folder_id
):
    # Primary title "Saga"; the release names an alternate title only.
    series_id = await make_series(
        db,
        format_profile_id=format_profile_id,
        root_folder_id=root_folder_id,
        title="Saga",
        aliases=json.dumps(["Cosmic Odyssey"]),
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")
    await make_indexer(db)

    result = await _run(
        db, db.db_path.parent, feed_handler("Cosmic Odyssey 007 (2012)"),
        series_id=series_id, issue_id=issue_id,
    )
    assert result is not None
    assert result.approved, "the release maps to the series through its alias"
    assert result.approved[0].mapped_series_id == series_id
    assert result.approved[0].mapped_issue_id == issue_id


@pytest.mark.req("FRG-SRCH-003")
async def test_without_the_alias_the_same_release_is_unmapped(
    db, format_profile_id, root_folder_id
):
    # Same series, no aliases -> the alternate-title release maps to nothing.
    series_id = await make_series(
        db,
        format_profile_id=format_profile_id,
        root_folder_id=root_folder_id,
        title="Saga",
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")
    await make_indexer(db)

    result = await _run(
        db, db.db_path.parent, feed_handler("Cosmic Odyssey 007 (2012)"),
        series_id=series_id, issue_id=issue_id,
    )
    assert result is not None
    assert not result.approved
    assert result.decisions and result.decisions[0].reasons


@pytest.mark.req("FRG-SRCH-003")
async def test_edit_series_replaces_aliases(
    db, format_profile_id, root_folder_id
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    # Set, then clear — the edit path maintains the user-editable list.
    await edit_series(db, series_id, aliases=["Alt One", " Alt Two ", "Alt One"])
    async with db.read_session() as session:
        row = await repo.get_series(session, series_id)
        # De-duplicated + trimmed, order preserved.
        assert decode_aliases(row.aliases) == ("Alt One", "Alt Two")

    await edit_series(db, series_id, aliases=[])
    async with db.read_session() as session:
        row = await repo.get_series(session, series_id)
        assert decode_aliases(row.aliases) == ()
        assert row.aliases is None  # empty clears to NULL


@pytest.mark.req("FRG-SRCH-003")
def test_aliases_round_trip_through_the_series_api(tmp_path):
    """The existing series edit path (PUT) accepts and returns aliases."""
    from functools import partial
    from pathlib import Path

    from fastapi.testclient import TestClient

    from foragerr.app import create_app
    from foragerr.library import repo as library_repo
    from .support import profile_id

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(make_settings(cfg))
    with TestClient(app) as client:
        db = app.state.db

        async def _seed(db):
            pid = await profile_id(db)
            root = Path(db.db_path.parent) / "root"
            root.mkdir(exist_ok=True)
            async with db.write_session() as session:
                rf = await library_repo.create_root_folder(session, str(root))
                rid = rf.id
            return await make_series(
                db, format_profile_id=pid, root_folder_id=rid
            )

        series_id = client.portal.call(partial(_seed, db))

        # Freshly-added series has no aliases.
        got = client.get(f"/api/v1/series/{series_id}").json()
        assert got["aliases"] == []

        # PUT sets them; the resource echoes them back.
        resp = client.put(
            f"/api/v1/series/{series_id}", json={"aliases": ["Cosmic Odyssey", "TCO"]}
        )
        assert resp.status_code == 200
        assert resp.json()["aliases"] == ["Cosmic Odyssey", "TCO"]
        assert client.get(f"/api/v1/series/{series_id}").json()["aliases"] == [
            "Cosmic Odyssey",
            "TCO",
        ]
