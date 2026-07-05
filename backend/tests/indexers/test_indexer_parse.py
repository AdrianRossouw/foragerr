"""Newznab response parsing, normalization, dedup, error mapping
(FRG-IDX-006, FRG-IDX-007, FRG-SEC-002)."""

from __future__ import annotations

import pytest

from foragerr.indexers.errors import IndexerAuthError, IndexerLimitError, IndexerUnavailable
from foragerr.indexers.parse import IndexerContext, parse_newznab_feed
from indexers_support import error_doc, feed_item, newznab_feed

CTX = IndexerContext(indexer_id=3, indexer_name="DogNZB", indexer_priority=10)


@pytest.mark.req("FRG-IDX-006")
@pytest.mark.req("FRG-IDX-007")
def test_valid_feed_yields_fully_populated_candidates():
    feed = newznab_feed(
        feed_item(
            guid="g1",
            title="Saga 007 (2025) (Digital)",
            url="https://idx.test/nzb/g1",
            size=104857600,
            category=7030,
            extra_attrs={"grabs": "12"},
        )
    )
    result = parse_newznab_feed(feed, CTX, query_tier=2)
    assert result.skipped == 0
    [c] = result.candidates
    assert c.guid == "g1"
    assert c.title == "Saga 007 (2025) (Digital)"
    assert c.link == "https://idx.test/nzb/g1"
    assert c.size_bytes == 104857600
    assert c.categories == (7030,)
    assert c.attributes["grabs"] == "12"
    assert "category" not in c.attributes  # promoted to typed categories
    assert c.pub_date is not None
    # Attribution stamped from the context (FRG-IDX-007).
    assert (c.indexer_id, c.indexer_name, c.indexer_priority) == (3, "DogNZB", 10)
    assert c.query_tier == 2


@pytest.mark.req("FRG-IDX-007")
def test_duplicate_guid_from_one_indexer_collapses():
    feed = newznab_feed(
        feed_item(guid="dupe", title="A"),
        feed_item(guid="dupe", title="A (again)"),
        feed_item(guid="other", title="B"),
    )
    result = parse_newznab_feed(feed, CTX)
    guids = [c.guid for c in result.candidates]
    assert guids == ["dupe", "other"]


@pytest.mark.req("FRG-IDX-005")
@pytest.mark.req("FRG-IDX-007")
def test_guid_duplicates_are_counted_for_pagination():
    # A guid-duplicate is dropped from candidates but the indexer DID return it,
    # so it is counted separately — pagination reconstructs the true page size
    # from candidates + skipped + duplicates and does not fake a short page.
    feed = newznab_feed(
        feed_item(guid="dupe", title="A"),
        feed_item(guid="dupe", title="A (again)"),
        feed_item(guid="other", title="B"),
    )
    result = parse_newznab_feed(feed, CTX)
    assert result.duplicates == 1
    assert result.skipped == 0
    assert len(result.candidates) + result.skipped + result.duplicates == 3


@pytest.mark.req("FRG-IDX-006")
def test_malformed_items_skipped_and_counted_batch_survives():
    feed = newznab_feed(
        feed_item(guid="ok1", title="Good"),
        "<item><title>no guid or link</title></item>",  # malformed
        feed_item(guid="ok2", title="Good 2"),
    )
    result = parse_newznab_feed(feed, CTX)
    assert result.skipped == 1
    assert [c.guid for c in result.candidates] == ["ok1", "ok2"]


@pytest.mark.req("FRG-IDX-006")
def test_error_code_100_maps_to_typed_auth_failure():
    with pytest.raises(IndexerAuthError):
        parse_newznab_feed(error_doc(100, "Incorrect user credentials"), CTX)


@pytest.mark.req("FRG-IDX-006")
def test_error_code_500_maps_to_typed_limit_failure():
    with pytest.raises(IndexerLimitError):
        parse_newznab_feed(error_doc(500, "Request limit reached"), CTX)


@pytest.mark.req("FRG-IDX-006")
def test_other_error_code_maps_to_typed_unavailable():
    with pytest.raises(IndexerUnavailable):
        parse_newznab_feed(error_doc(300, "No such item"), CTX)


@pytest.mark.req("FRG-IDX-007")
def test_cross_indexer_duplicates_not_collapsed_here():
    # The same content from two indexers: distinct contexts, distinct seen-sets,
    # both survive normalization (cross-indexer dedup is a decision-level job).
    ctx_a = IndexerContext(indexer_id=1, indexer_name="A", indexer_priority=1)
    ctx_b = IndexerContext(indexer_id=2, indexer_name="B", indexer_priority=2)
    item = feed_item(guid="shared", title="Same Release")
    a = parse_newznab_feed(newznab_feed(item), ctx_a)
    b = parse_newznab_feed(newznab_feed(item), ctx_b)
    assert a.candidates[0].indexer_id == 1
    assert b.candidates[0].indexer_id == 2


@pytest.mark.req("FRG-IDX-007")
def test_size_falls_back_to_enclosure_length():
    # No newznab size attr -> enclosure length is used.
    item = (
        "<item><title>T</title><guid>x</guid>"
        '<enclosure url="https://idx.test/x" length="777" type="application/x-nzb"/>'
        "</item>"
    )
    result = parse_newznab_feed(newznab_feed(item), CTX)
    assert result.candidates[0].size_bytes == 777
