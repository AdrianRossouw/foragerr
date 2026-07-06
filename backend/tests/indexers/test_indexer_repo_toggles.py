"""Indexer persistence + per-path usage toggles (FRG-IDX-001, FRG-IDX-002)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from foragerr.indexers.models import IndexerRow
from foragerr.indexers.repo import create_indexer, list_indexers, select_for_path
from indexers_support import newznab_settings


@pytest.mark.req("FRG-IDX-001")
async def test_two_newznab_rows_coexist_in_one_table(db):
    await create_indexer(
        db,
        name="DogNZB",
        implementation="newznab",
        settings=newznab_settings(base_url="https://api.dognzb.cr", api_key="k1"),
        priority=10,
    )
    await create_indexer(
        db,
        name="NZB.su",
        implementation="newznab",
        settings=newznab_settings(base_url="https://api.nzb.su", api_key="k2"),
        priority=25,
    )
    async with db.read_session() as session:
        rows = (await session.execute(select(IndexerRow))).scalars().all()
    assert len(rows) == 2
    assert {r.name for r in rows} == {"DogNZB", "NZB.su"}
    assert all(r.implementation == "newznab" for r in rows)
    # Each carries its own priority and its settings serialized as JSON.
    assert {r.priority for r in rows} == {10, 25}
    assert all(r.settings.startswith("{") for r in rows)


@pytest.mark.req("FRG-IDX-002")
async def test_automatic_search_honors_the_automatic_toggle(db):
    await create_indexer(
        db, name="A", implementation="newznab",
        settings=newznab_settings(), enable_auto=False,
    )
    await create_indexer(
        db, name="B", implementation="newznab",
        settings=newznab_settings(), enable_auto=True,
    )
    rows = await list_indexers(db)
    selected = select_for_path(rows, "auto")
    assert [r.name for r in selected] == ["B"]


@pytest.mark.req("FRG-IDX-002")
async def test_interactive_path_is_gated_independently_of_automatic(db):
    await create_indexer(
        db, name="A", implementation="newznab",
        settings=newznab_settings(), enable_auto=False, enable_interactive=True,
    )
    rows = await list_indexers(db)
    assert [r.name for r in select_for_path(rows, "auto")] == []
    assert [r.name for r in select_for_path(rows, "interactive")] == ["A"]


@pytest.mark.req("FRG-IDX-002")
async def test_disabled_indexer_excluded_from_every_path(db):
    await create_indexer(
        db, name="Off", implementation="newznab",
        settings=newznab_settings(), enabled=False,
    )
    rows = await list_indexers(db)
    for path in ("rss", "auto", "interactive"):
        assert select_for_path(rows, path) == []


@pytest.mark.req("FRG-IDX-002")
async def test_rss_toggle_persists_without_gating_an_m1_path(db):
    row = await create_indexer(
        db, name="R", implementation="newznab",
        settings=newznab_settings(), enable_rss=False,
    )
    assert row.enable_rss is False
    rows = await list_indexers(db)
    # RSS toggle persisted on the row (schema-forward); still queryable by other
    # paths since RSS sync itself is a later milestone.
    assert select_for_path(rows, "rss") == []
    assert [r.name for r in select_for_path(rows, "auto")] == ["R"]
