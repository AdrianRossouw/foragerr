"""Newznab capabilities probe, caching, and degraded defaults (FRG-IDX-004)."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from foragerr.indexers.caps import (
    CONSERVATIVE_CAPS,
    Capabilities,
    CapsCache,
    parse_caps,
)
from foragerr.indexers.models import IndexerRow
from foragerr.indexers.repo import create_indexer
from foragerr.indexers.service import refresh_caps
from foragerr.indexers.settings import COMICS_CATEGORY
from indexers_support import caps_doc, make_factory, newznab_settings


@pytest.mark.req("FRG-IDX-004")
def test_parse_caps_reads_limits_categories_and_modes():
    caps = parse_caps(caps_doc())
    assert caps.page_size_max == 100
    assert caps.page_size_default == 75
    assert caps.categories[7030] == "Comics"
    assert caps.search_available
    assert caps.book_search_available
    assert not caps.degraded


@pytest.mark.req("FRG-IDX-004")
def test_resolve_categories_defaults_to_7030_with_fallback():
    caps = parse_caps(caps_doc())
    assert caps.resolve_categories([7030]) == [7030]
    # A category the indexer does not offer falls back to 7030 conservatively.
    assert caps.resolve_categories([9999]) == [COMICS_CATEGORY]


@pytest.mark.req("FRG-IDX-004")
def test_caps_cache_reuses_within_ttl_and_expires():
    now = {"t": 0.0}
    cache = CapsCache(ttl_seconds=100.0, clock=lambda: now["t"])
    caps = Capabilities(categories={7030: "Comics"})
    cache.put(1, caps)
    assert cache.get(1) is caps  # within TTL, reused (no re-fetch)
    now["t"] = 101.0
    assert cache.get(1) is None  # expired past the lifetime


@pytest.mark.req("FRG-IDX-004")
def test_parse_caps_tolerates_hostile_int_attribute():
    # "--5" slips past a naive lstrip('-')/isdigit guard yet raises inside
    # int(); the parser must degrade to the default rather than raise (an
    # unhandled parse would surface as a 500 from /indexer/test, not a 400).
    xml = (
        b"<caps>"
        b'<limits max="--5" default="oops"/>'
        b'<category id="7030" name="Comics"/>'
        b'<category id="--9" name="Bad"/>'
        b"</caps>"
    )
    caps = parse_caps(xml)  # must not raise
    assert caps.page_size_max == 100  # DEFAULT_PAGE_SIZE fallback
    assert caps.page_size_default == 100
    assert caps.categories == {7030: "Comics"}  # the hostile id is dropped


@pytest.mark.req("FRG-IDX-004")
async def test_degraded_caps_pinned_only_briefly():
    # A failed probe caches the conservative fallback under the SHORT degraded
    # TTL, so a transient failure re-probes soon rather than being pinned for
    # the 7-day success lifetime.
    from foragerr.indexers.caps import DEGRADED_CAPS_TTL_SECONDS
    from foragerr.indexers.errors import IndexerUnavailable
    from foragerr.indexers.service import _resolve_caps

    now = {"t": 0.0}
    cache = CapsCache(clock=lambda: now["t"])  # default 7-day success TTL

    class _FailingClient:
        async def caps(self):
            raise IndexerUnavailable("probe boom")

    caps = await _resolve_caps(_FailingClient(), 5, cache)
    assert caps.degraded
    assert cache.get(5) is not None  # cached right after the failure

    now["t"] = DEGRADED_CAPS_TTL_SECONDS + 1
    assert cache.get(5) is None  # expired at the short TTL -> will re-probe

    # A live probe of a different indexer at the same instant is still valid,
    # proving the short TTL is specific to the degraded entry.
    cache.put(6, Capabilities(categories={7030: "Comics"}))
    now["t"] += DEGRADED_CAPS_TTL_SECONDS + 1
    assert cache.get(6) is not None


@pytest.mark.req("FRG-IDX-004")
def test_conservative_defaults_are_marked_degraded():
    assert CONSERVATIVE_CAPS.degraded
    assert CONSERVATIVE_CAPS.resolve_categories([7030]) == [7030]


@pytest.mark.req("FRG-IDX-004")
async def test_probe_failure_degrades_and_records_on_the_row(db):
    # An indexer whose caps probe returns an auth error must degrade to
    # conservative defaults and record that state on the row, not block.
    row = await create_indexer(
        db, name="Idx", implementation="newznab", settings=newznab_settings()
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    factory, _ = make_factory(db_path_tmp(db), handler)
    caps = await refresh_caps(db, row, factory=factory)
    assert caps.degraded

    async with db.read_session() as session:
        refreshed = (await session.execute(select(IndexerRow))).scalars().one()
    assert refreshed.caps_degraded is True
    assert refreshed.caps_fetched_at is not None


@pytest.mark.req("FRG-IDX-004")
async def test_successful_probe_records_live_caps_on_the_row(db):
    row = await create_indexer(
        db, name="Idx", implementation="newznab", settings=newznab_settings()
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=caps_doc())

    factory, _ = make_factory(db_path_tmp(db), handler)
    caps = await refresh_caps(db, row, factory=factory)
    assert not caps.degraded
    assert caps.categories[7030] == "Comics"

    async with db.read_session() as session:
        refreshed = (await session.execute(select(IndexerRow))).scalars().one()
    assert refreshed.caps_degraded is False
    assert "7030" in refreshed.caps_json


def db_path_tmp(db) -> "object":
    """The config dir of the test db (its parent) — a real dir make_factory
    only needs to root a Settings object."""
    return db.db_path.parent
