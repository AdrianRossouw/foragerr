"""Tiered Newznab query generation (FRG-IDX-005)."""

from __future__ import annotations

import pytest

from foragerr.indexers.query import SearchTarget, build_queries, clean_query_term


@pytest.mark.req("FRG-IDX-005")
def test_cleaned_title_normalizes_punctuation_and_ampersand():
    assert clean_query_term("Spider-Man & The X-Men!") == "Spider Man and The X Men"


@pytest.mark.req("FRG-IDX-005")
def test_cleaned_title_strips_html_from_cv_text():
    # Routed through the change-3 sanitizer: raw markup never reaches the wire.
    assert clean_query_term("<b>Saga</b>") == "Saga"


@pytest.mark.req("FRG-IDX-005")
def test_tiered_variants_pad_issue_and_tag_year_and_volume():
    specs = build_queries(
        SearchTarget(series_title="Saga", issue_number="7", year=2012, volume=1)
    )
    texts = {(s.tier, s.text) for s in specs}
    # Tier 0 (most specific): title + padded issue + year.
    assert (0, "Saga 007 2012") in texts
    assert (0, "Saga 7 2012") in texts
    # Tier 1: title + issue + volume tag.
    assert (1, "Saga 007 v1") in texts
    # Tier 2: title + issue, padding variants 007/07/7.
    assert {(2, "Saga 007"), (2, "Saga 07"), (2, "Saga 7")} <= texts
    # Tier 3: bare title (broadest).
    assert (3, "Saga") in texts


@pytest.mark.req("FRG-IDX-005")
def test_tiers_are_ordered_most_specific_first():
    specs = build_queries(
        SearchTarget(series_title="Saga", issue_number="7", year=2012, volume=1)
    )
    tiers = [s.tier for s in specs]
    assert tiers == sorted(tiers)  # non-decreasing: tier 0 first
    assert specs[0].tier == 0
    assert specs[-1].tier == 3


@pytest.mark.req("FRG-IDX-005")
def test_non_integer_issue_kept_verbatim():
    specs = build_queries(SearchTarget(series_title="Saga", issue_number="1.MU"))
    assert any(s.text == "Saga 1.MU" for s in specs)
    # No bogus zero-padding of a suffixed issue.
    assert not any("001.MU" in s.text for s in specs)


@pytest.mark.req("FRG-IDX-005")
def test_title_only_target_yields_single_broad_query():
    specs = build_queries(SearchTarget(series_title="Saga"))
    assert [(s.tier, s.text) for s in specs] == [(3, "Saga")]
