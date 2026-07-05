"""Indexer search entrypoint end-to-end (FRG-IDX-004..010, FRG-NFR-005)."""

from __future__ import annotations

import httpx
import pytest

from foragerr.indexers.caps import CapsCache
from foragerr.indexers.query import SearchTarget
from foragerr.indexers.service import search_indexer
from foragerr.providers.backoff import (
    FAST_FORWARD_MIN_LEVEL,
    PROVIDER_INDEXER,
    ProviderBackoff,
)
from indexers_support import (  # noqa: F401 (_reset_indexer_gates is autouse)
    _reset_indexer_gates,
    caps_doc,
    feed_item,
    make_factory,
    make_indexer_row,
    newznab_feed,
)

FAST = 0.0  # clamped to the gate floor; keeps the many-query test snappy


def _tmp(db):
    return db.db_path.parent


def feed_handler(*, search_status: int = 200):
    """A handler serving caps + one unique item per (query, first page)."""

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        t = params.get("t")
        if t == "caps":
            return httpx.Response(200, content=caps_doc())
        if search_status != 200:
            return httpx.Response(search_status)
        if int(params.get("offset", "0")) > 0:
            return httpx.Response(200, content=newznab_feed())  # empty next page
        q = params.get("q")
        return httpx.Response(
            200, content=newznab_feed(feed_item(guid=q, title=q))
        )

    return handler


@pytest.mark.req("FRG-IDX-005")
@pytest.mark.req("FRG-IDX-006")
async def test_search_returns_tier_stamped_candidates(db):
    factory, transport = make_factory(_tmp(db), feed_handler())
    row = make_indexer_row(id=1, priority=10)
    outcome = await search_indexer(
        row,
        SearchTarget(series_title="Saga", issue_number="7", year=2012, volume=1),
        factory=factory,
        backoff=ProviderBackoff(db),
        caps_cache=CapsCache(),
        min_interval=FAST,
    )
    assert outcome.failure is None
    assert not outcome.backing_off
    assert outcome.candidates
    # Every query tier that produced a result is stamped on its candidates.
    tiers = {c.query_tier for c in outcome.candidates}
    assert tiers == {0, 1, 2, 3}
    # Attribution carried from the row.
    assert all(c.indexer_id == 1 and c.indexer_priority == 10 for c in outcome.candidates)


@pytest.mark.req("FRG-IDX-009")
async def test_retention_passed_as_maxage_on_the_query(db):
    factory, transport = make_factory(_tmp(db), feed_handler())
    row = make_indexer_row(id=1)
    await search_indexer(
        row,
        SearchTarget(series_title="Saga"),
        factory=factory,
        backoff=ProviderBackoff(db),
        caps_cache=CapsCache(),
        retention_days=3000,
        min_interval=FAST,
    )
    search_requests = [
        r for r in transport.requests if r.url.params.get("t") == "search"
    ]
    assert search_requests
    assert all(r.url.params.get("maxage") == "3000" for r in search_requests)


@pytest.mark.req("FRG-IDX-009")
async def test_per_indexer_retention_override_wins(db):
    factory, transport = make_factory(_tmp(db), feed_handler())
    row = make_indexer_row(id=1, retention_override=1200)
    await search_indexer(
        row,
        SearchTarget(series_title="Saga"),
        factory=factory,
        backoff=ProviderBackoff(db),
        caps_cache=CapsCache(),
        retention_days=3000,  # global — overridden by the row's 1200
        min_interval=FAST,
    )
    search = [r for r in transport.requests if r.url.params.get("t") == "search"]
    assert all(r.url.params.get("maxage") == "1200" for r in search)


@pytest.mark.req("FRG-IDX-010")
@pytest.mark.req("FRG-NFR-005")
async def test_request_failure_escalates_the_backoff_ladder(db):
    factory, transport = make_factory(_tmp(db), feed_handler(search_status=401))
    backoff = ProviderBackoff(db)
    row = make_indexer_row(id=1)
    outcome = await search_indexer(
        row,
        SearchTarget(series_title="Saga"),
        factory=factory,
        backoff=backoff,
        caps_cache=CapsCache(),
        min_interval=FAST,
    )
    assert outcome.failure is not None
    assert not outcome.candidates
    status = await backoff.status(PROVIDER_INDEXER, 1)
    assert status.active
    assert status.level == FAST_FORWARD_MIN_LEVEL  # auth failure fast-forwards


@pytest.mark.req("FRG-IDX-010")
@pytest.mark.req("FRG-NFR-005")
async def test_backing_off_indexer_is_skipped_with_no_request(db):
    factory, transport = make_factory(_tmp(db), feed_handler())
    backoff = ProviderBackoff(db)
    # Put the indexer into a back-off window first.
    await backoff.record_failure(PROVIDER_INDEXER, 1, reason="prior failure")
    row = make_indexer_row(id=1)
    outcome = await search_indexer(
        row,
        SearchTarget(series_title="Saga"),
        factory=factory,
        backoff=backoff,
        caps_cache=CapsCache(),
        min_interval=FAST,
    )
    assert outcome.backing_off
    assert not outcome.candidates
    assert transport.requests == []  # no HTTP request was issued


@pytest.mark.req("FRG-IDX-010")
async def test_success_resets_backoff_after_a_prior_failure(db):
    backoff = ProviderBackoff(db)
    await backoff.record_failure(PROVIDER_INDEXER, 1, reason="x")
    # Advance past the window by using a healthy indexer id search that succeeds.
    factory, _ = make_factory(_tmp(db), feed_handler())
    row = make_indexer_row(id=2)  # a different, healthy indexer
    outcome = await search_indexer(
        row,
        SearchTarget(series_title="Saga"),
        factory=factory,
        backoff=backoff,
        caps_cache=CapsCache(),
        min_interval=FAST,
    )
    assert outcome.failure is None
    assert not (await backoff.status(PROVIDER_INDEXER, 2)).active


@pytest.mark.req("FRG-IDX-004")
async def test_caps_probe_failure_degrades_but_search_continues(db):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("t") == "caps":
            return httpx.Response(500)  # caps unavailable
        if int(request.url.params.get("offset", "0")) > 0:
            return httpx.Response(200, content=newznab_feed())
        return httpx.Response(
            200, content=newznab_feed(feed_item(guid="g", title="Saga"))
        )

    factory, _ = make_factory(_tmp(db), handler)
    outcome = await search_indexer(
        make_indexer_row(id=1),
        SearchTarget(series_title="Saga"),
        factory=factory,
        backoff=ProviderBackoff(db),
        caps_cache=CapsCache(),
        min_interval=FAST,
    )
    # Degraded caps recorded on the outcome; the search still ran and returned.
    assert outcome.degraded_caps
    assert outcome.candidates
    assert outcome.failure is None


@pytest.mark.req("FRG-IDX-005")
async def test_guid_dupes_on_a_full_page_do_not_stop_pagination(db):
    # A full first page whose last item duplicates an earlier guid must still be
    # treated as a full page (candidates + duplicates == limit) so paging
    # CONTINUES to the next page rather than faking a short page and stopping.
    # caps_doc's default page size is 75.
    page_size = 75

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("t") == "caps":
            return httpx.Response(200, content=caps_doc())
        offset = int(params.get("offset", "0"))
        if offset == 0:
            # 74 unique + 1 duplicate of g0 == a full page of `page_size` items.
            items = [feed_item(guid=f"g{i}", title=f"T{i}") for i in range(page_size - 1)]
            items.append(feed_item(guid="g0", title="dup of g0"))
            return httpx.Response(200, content=newznab_feed(*items))
        if offset >= page_size:
            # The next page carries a fresh release only reachable if paging
            # continued past the duplicate-padded first page.
            return httpx.Response(
                200, content=newznab_feed(feed_item(guid="page2", title="Page2"))
            )
        return httpx.Response(200, content=newznab_feed())

    factory, transport = make_factory(_tmp(db), handler)
    outcome = await search_indexer(
        make_indexer_row(id=1),
        SearchTarget(series_title="Saga"),  # bare title -> a single query tier
        factory=factory,
        backoff=ProviderBackoff(db),
        caps_cache=CapsCache(),
        min_interval=FAST,
    )
    guids = {c.guid for c in outcome.candidates}
    assert "page2" in guids, "pagination must continue past a dupe-filled full page"
    search_offsets = [
        int(r.url.params.get("offset", "0"))
        for r in transport.requests
        if r.url.params.get("t") == "search"
    ]
    assert any(o >= page_size for o in search_offsets)
