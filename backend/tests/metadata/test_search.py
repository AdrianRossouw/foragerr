"""Series search: plausibility annotations, publisher ignore-list, bounded
truncation (FRG-META-007). Also covers the bounded suggest variant
(FRG-API-017): a single-page fetch that NEVER walks, carries ``complete``
but no ``truncated``."""

from __future__ import annotations

import logging

import httpx
import pytest

from cv_support import _reset_gate, json_response, make_client  # noqa: F401
from fixtures import search_envelope, volume_payload


def _volumes():
    return [
        volume_payload(id=1, name="Saga", publisher={"name": "Image Comics"},
                       start_year="2012", issues=[{"id": 1}] * 60),
        volume_payload(id=2, name="Saga of the Swamp Thing",
                       publisher={"name": "DC Comics"}, start_year="1985",
                       issues=[{"id": 1}] * 171),
        volume_payload(id=3, name="Saga Variant Reprints",
                       publisher={"name": "Reprint House"}, start_year="2020",
                       issues=[{"id": 1}] * 3),
    ]


@pytest.mark.req("FRG-META-007")
async def test_candidates_annotated_no_auto_pick(tmp_path):
    client, _ = make_client(
        tmp_path,
        lambda r: json_response(search_envelope(_volumes(), total=3)),
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        result = await client.search_series("Saga 2012")

    # returns a candidate LIST, does not select one
    assert len(result.candidates) >= 2
    by_id = {c.series.cv_volume_id: c for c in result.candidates}
    exact = by_id[1]
    swamp = by_id[2]
    assert exact.plausibility.year_proximity == 0  # 2012 vs query year 2012
    assert swamp.plausibility.year_proximity == 27  # 1985 vs 2012
    assert exact.plausibility.name_similarity > swamp.plausibility.name_similarity
    assert exact.plausibility.haveit is False  # library flag left to the caller


@pytest.mark.req("FRG-META-007")
async def test_ignored_publisher_excluded_others_only_annotated(tmp_path):
    client, _ = make_client(
        tmp_path,
        lambda r: json_response(search_envelope(_volumes(), total=3)),
        comicvine_ignored_publishers="Reprint House, Some Other Imprint",
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        result = await client.search_series("Saga")
    ids = {c.series.cv_volume_id for c in result.candidates}
    assert 3 not in ids  # ignored-publisher volume hard-dropped
    assert {1, 2} <= ids  # the rest survive, merely annotated


@pytest.mark.req("FRG-META-007")
async def test_target_issue_plausibility_annotation(tmp_path):
    client, _ = make_client(
        tmp_path,
        lambda r: json_response(search_envelope(_volumes(), total=3)),
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        result = await client.search_series("Saga", target_issue="150")
    by_id = {c.series.cv_volume_id: c for c in result.candidates}
    assert by_id[1].plausibility.target_issue_plausible is False  # only 60 issues
    assert by_id[2].plausibility.target_issue_plausible is True  # 171 issues


@pytest.mark.req("FRG-META-007")
async def test_bounded_result_cap_with_truncation_warning(tmp_path, caplog):
    client, _ = make_client(
        tmp_path,
        lambda r: json_response(search_envelope(_volumes(), total=3)),
        comicvine_search_result_cap=2,
        comicvine_min_interval_seconds=0.05,
    )
    with caplog.at_level(logging.WARNING, logger="foragerr.metadata.comicvine"):
        async with client:
            result = await client.search_series("Saga")
    assert result.truncated is True
    assert len(result.candidates) <= 2
    assert any("truncat" in r.getMessage().lower() for r in caplog.records)


# --- suggest (FRG-API-017) ---------------------------------------------------
#
# `suggest_series` is a cheap, bounded first-page-only accelerator over
# `search_series` — it must NEVER enter `_paginate`'s multi-page walk, so
# every test below asserts at most one upstream request landed.


@pytest.mark.req("FRG-API-017")
async def test_suggest_series_issues_at_most_one_upstream_request(tmp_path):
    client, transport = make_client(
        tmp_path,
        lambda r: json_response(search_envelope(_volumes(), total=3)),
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        result = await client.suggest_series("Saga")

    # the load-bearing guarantee: the walk is never entered
    assert len(transport.requests) == 1
    req = transport.requests[0]
    assert req.url.params["offset"] == "0"
    assert int(req.url.params["limit"]) <= 10
    assert result.complete is True
    assert len(result.candidates) == 3


@pytest.mark.req("FRG-API-017")
async def test_suggest_series_neutralises_filter_metacharacters(tmp_path):
    client, transport = make_client(
        tmp_path,
        lambda r: json_response(search_envelope([], total=0)),
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        await client.suggest_series("Saga, Vol: 2")

    assert len(transport.requests) == 1
    filter_value = transport.requests[0].url.params["filter"]
    assert filter_value == "name:Saga  Vol  2"
    assert "," not in filter_value
    assert ":" not in filter_value.removeprefix("name:")


@pytest.mark.req("FRG-API-017")
async def test_suggest_series_mid_fetch_failure_is_incomplete_no_candidates(
    tmp_path,
):
    client, transport = make_client(
        tmp_path,
        lambda r: httpx.Response(500, content=b"upstream error"),
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        result = await client.suggest_series("Saga")

    # still only one request — a single failed page, never a retry/walk
    assert len(transport.requests) == 1
    assert result.complete is False
    assert result.candidates == ()


@pytest.mark.req("FRG-API-017")
async def test_suggest_series_auth_failure_propagates(tmp_path):
    """Mirrors `_paginate`'s auth carve-out (FRG-META-004): a credential
    failure must not be swallowed into a `complete=False` empty result — the
    API route relies on this to map it to its own 503 rather than a 200."""
    from foragerr.metadata.errors import ComicVineAuthError

    client, transport = make_client(
        tmp_path,
        lambda r: httpx.Response(401, content=b"unauthorized"),
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        with pytest.raises(ComicVineAuthError):
            await client.suggest_series("Saga")
    assert len(transport.requests) == 1


@pytest.mark.req("FRG-API-017")
async def test_suggest_series_caps_at_ten_even_if_upstream_overserves(tmp_path):
    volumes = [
        volume_payload(id=i, name=f"Saga {i}", start_year="2012") for i in range(15)
    ]
    client, transport = make_client(
        tmp_path,
        lambda r: json_response(search_envelope(volumes, total=15)),
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        result = await client.suggest_series("Saga")

    assert len(transport.requests) == 1
    assert len(result.candidates) == 10


@pytest.mark.req("FRG-API-017")
async def test_suggest_series_drops_ignored_publisher_volumes(tmp_path):
    client, transport = make_client(
        tmp_path,
        lambda r: json_response(search_envelope(_volumes(), total=3)),
        comicvine_ignored_publishers="Reprint House",
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        result = await client.suggest_series("Saga")

    assert len(transport.requests) == 1
    ids = {c.cv_volume_id for c in result.candidates}
    assert 3 not in ids  # ignored-publisher volume hard-dropped
    assert {1, 2} <= ids
