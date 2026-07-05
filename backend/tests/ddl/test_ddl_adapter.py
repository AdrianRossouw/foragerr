"""Versioned GetComics adapter tests against committed fixtures (FRG-DDL-003)."""

from __future__ import annotations

import pytest

from foragerr.ddl.adapter_v1 import parse_post_page, parse_search_page
from foragerr.ddl.errors import AdapterDrift
from ddl_support import fixture

BASE = "https://getcomics.org"


@pytest.mark.req("FRG-DDL-003")
def test_adapter_parses_recorded_search_page_into_candidates():
    page = parse_search_page(fixture("search_page1.html"), base_url=BASE)
    titles = [p.title for p in page.posts]
    assert "Example Comic #1 (2024)" in titles
    first = page.posts[0]
    assert first.post_url == "https://getcomics.org/comic/example-comic-1-2024/"
    assert first.size_bytes == int(45 * 1024**2)
    assert first.year == 2024
    assert first.pub_date is not None
    # The "older posts" link is resolved absolute for pagination.
    assert page.next_page_url == "https://getcomics.org/page/2/?s=example+comic"


@pytest.mark.req("FRG-DDL-003")
def test_adapter_flags_weekly_roundup_posts():
    page = parse_search_page(fixture("search_page1.html"), base_url=BASE)
    roundups = [p for p in page.posts if p.is_roundup]
    assert [p.title for p in roundups] == ["Marvel Weekly Pack May 2024"]


@pytest.mark.req("FRG-DDL-003")
def test_adapter_parses_recorded_post_page_links():
    links = parse_post_page(fixture("post_page.html"), base_url=BASE)
    urls = [l.url for l in links]
    # Relative hrefs resolved absolute; every anchor (incl. paywall) surfaced
    # raw here — host/quality typing + paywall rejection happen in links.py.
    assert "https://getcomics.org/dlds/run.php?id=1001&q=up" in urls
    assert any("sh.st" in u for u in urls)
    assert any(l.host_label.lower() == "read online" for l in links)


@pytest.mark.req("FRG-DDL-003")
def test_empty_but_wellformed_search_is_zero_results_not_drift():
    page = parse_search_page(fixture("search_empty.html"), base_url=BASE)
    assert page.posts == []
    assert page.next_page_url is None


@pytest.mark.req("FRG-DDL-003")
def test_drifted_search_layout_raises_typed_adapter_drift():
    with pytest.raises(AdapterDrift) as excinfo:
        parse_search_page(fixture("search_drifted.html"), base_url=BASE)
    assert excinfo.value.kind == "search"


@pytest.mark.req("FRG-DDL-003")
def test_drifted_post_layout_raises_typed_adapter_drift():
    with pytest.raises(AdapterDrift) as excinfo:
        parse_post_page(fixture("post_drifted.html"), base_url=BASE)
    assert excinfo.value.kind == "post"
