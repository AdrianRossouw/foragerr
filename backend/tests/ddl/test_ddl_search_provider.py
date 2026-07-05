"""GetComics search provider: ladder, pagination, dedup, roundup skip,
shared-engine candidates, and self-protection (FRG-DDL-002/003/006)."""

from __future__ import annotations

import json

import httpx
import pytest

from foragerr.db.base import utcnow
from foragerr.ddl.search_provider import build_query_ladder, search_getcomics
from foragerr.ddl.settings import GetComicsSettings
from foragerr.indexers.models import IndexerRow
from foragerr.indexers.query import SearchTarget
from foragerr.providers.backoff import PROVIDER_DDL, ProviderBackoff
from foragerr.releases import ReleaseCandidate
from ddl_support import fixture, make_factory


def _provider_row(**settings) -> IndexerRow:
    row = IndexerRow(
        name="GetComics",
        implementation="getcomics",
        protocol="ddl",
        priority=25,
        settings=json.dumps(GetComicsSettings(**settings).model_dump()),
        added_at=utcnow(),
    )
    row.id = 1
    return row


async def _noop_sleep(_: float) -> None:
    return None


async def _run(factory, db, target, row=None):
    return await search_getcomics(
        row or _provider_row(),
        target,
        factory=factory,
        backoff=ProviderBackoff(db),
        config_dir=None,
        sleep=_noop_sleep,
        clock=utcnow,
        rand=lambda: 0.0,
    )


TARGET = SearchTarget(series_title="Example Comic", issue_number="1", year=2024)


@pytest.mark.req("FRG-DDL-002")
def test_query_ladder_escalates_quoted_to_title_year():
    ladder = [q for _, q in build_query_ladder(TARGET)]
    assert ladder[0] == '"Example Comic #1 (2024)"'  # quoted exact first
    assert ladder[1] == "Example Comic #1 (2024)"  # unquoted
    assert "Example Comic #1" in ladder
    assert "Example Comic 2024" in ladder  # name + year (title-ward)


@pytest.mark.req("FRG-DDL-002")
async def test_pagination_dedup_and_roundup_skip(tmp_path, db):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.startswith("/page/2"):
            return httpx.Response(200, text=fixture("search_page2.html"))
        return httpx.Response(200, text=fixture("search_page1.html"))

    factory, _ = make_factory(tmp_path, handler)
    outcome = await _run(factory, db, TARGET)
    titles = [c.title for c in outcome.candidates]
    # post-1002 appears on both pages → emitted once; the weekly roundup is
    # skipped; page 2's unique post is followed via "older posts".
    assert titles.count("Example Comic #2 (2024) HD-Upscaled") == 1
    assert all("Weekly" not in t for t in titles)
    assert "Example Comic #3 (2024)" in titles


@pytest.mark.req("FRG-DDL-002")
async def test_candidates_are_plain_release_candidates_for_the_shared_engine(
    tmp_path, db
):
    factory, _ = make_factory(
        tmp_path, lambda req: httpx.Response(200, text=fixture("search_page1.html"))
    )
    outcome = await _run(factory, db, TARGET)
    assert outcome.candidates
    for candidate in outcome.candidates:
        # The SAME type Newznab emits — enters the one shared decision engine
        # with no DDL-private ranking; the page badge rides as an attribute.
        assert isinstance(candidate, ReleaseCandidate)
        assert candidate.guid == candidate.link  # post URL is the grab key
        assert candidate.indexer_id == 1
        assert candidate.attributes["source"] == "ddl"
        assert "ddl_quality" in candidate.attributes


@pytest.mark.req("FRG-DDL-003")
async def test_adapter_drift_yields_zero_results_health_and_backoff(tmp_path, db):
    factory, _ = make_factory(
        tmp_path, lambda req: httpx.Response(200, text=fixture("search_drifted.html"))
    )
    backoff = ProviderBackoff(db)
    outcome = await search_getcomics(
        _provider_row(), TARGET, factory=factory, backoff=backoff,
        config_dir=None, sleep=_noop_sleep, clock=utcnow, rand=lambda: 0.0,
    )
    assert outcome.candidates == []
    assert outcome.failure is not None  # degraded provider health
    assert (await backoff.status(PROVIDER_DDL, 1)).active  # ladder engaged


@pytest.mark.req("FRG-DDL-006")
async def test_http_429_engages_backoff(tmp_path, db):
    factory, _ = make_factory(tmp_path, lambda req: httpx.Response(429))
    backoff = ProviderBackoff(db)
    outcome = await search_getcomics(
        _provider_row(), TARGET, factory=factory, backoff=backoff,
        config_dir=None, sleep=_noop_sleep, clock=utcnow, rand=lambda: 0.0,
    )
    assert outcome.candidates == []
    status = await backoff.status(PROVIDER_DDL, 1)
    assert status.active and status.level >= 1


@pytest.mark.req("FRG-DDL-006")
async def test_cloudflare_challenge_engages_backoff(tmp_path, db):
    cf = "<html><body>Just a moment... cf-chl</body></html>"
    factory, _ = make_factory(tmp_path, lambda req: httpx.Response(200, text=cf))
    backoff = ProviderBackoff(db)
    outcome = await search_getcomics(
        _provider_row(), TARGET, factory=factory, backoff=backoff,
        config_dir=None, sleep=_noop_sleep, clock=utcnow, rand=lambda: 0.0,
    )
    assert outcome.candidates == []
    assert (await backoff.status(PROVIDER_DDL, 1)).active


@pytest.mark.req("FRG-DDL-006")
async def test_backing_off_provider_is_skipped_without_fetching(tmp_path, db):
    backoff = ProviderBackoff(db)
    await backoff.record_failure(PROVIDER_DDL, 1, reason="prior", fast_forward=True)
    factory, transport = make_factory(
        tmp_path, lambda req: httpx.Response(200, text=fixture("search_page1.html"))
    )
    outcome = await search_getcomics(
        _provider_row(), TARGET, factory=factory, backoff=backoff,
        config_dir=None, sleep=_noop_sleep, clock=utcnow, rand=lambda: 0.0,
    )
    assert outcome.backing_off is True
    assert transport.requests == []  # no page fetched while backing off
