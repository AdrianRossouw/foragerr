"""OpenSearch contract tests (FRG-OPDS-007 option a): the root feed's
``rel="search"`` link, the descriptor document, the templated round-trip into
the search feed, case-folded title/alias containment matching, the
empty-but-valid no-match feed, and q-preserving pagination. Hostile-input
cases live in ``test_opds_security.py``.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from foragerr.app import create_app
from foragerr.library.flows import encode_aliases
from foragerr.library.models import SeriesRow
from opds_support import opds_settings, seed, simple_series

ATOM = "{http://www.w3.org/2005/Atom}"
OS = "{http://a9.com/-/spec/opensearch/1.1/}"
OS_DESC_TYPE = "application/opensearchdescription+xml"
NAV_KIND = "application/atom+xml; profile=opds-catalog; kind=navigation"
ACQ_KIND = "application/atom+xml; profile=opds-catalog; kind=acquisition"


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return opds_settings(cfg)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def _seed(client, tmp_path, spec):
    return client.portal.call(seed, client.app, tmp_path / "library", spec)


async def _set_aliases(app, series_id: int, aliases: list[str]) -> None:
    async with app.state.db.write_session() as session:
        await session.execute(
            update(SeriesRow)
            .where(SeriesRow.id == series_id)
            .values(aliases=encode_aliases(aliases))
        )


def _search(client, q: str, **params):
    resp = client.get("/opds/search", params={"q": q, **params})
    assert resp.status_code == 200
    return ET.fromstring(resp.text)


def _entry_hrefs(feed) -> list[str]:
    return [
        e.find(f"{ATOM}link").get("href") for e in feed.findall(f"{ATOM}entry")
    ]


@pytest.mark.req("FRG-OPDS-007")
def test_descriptor_template_is_absolute_under_a_non_default_base_path(tmp_path):
    """Gate fix: the OpenSearch template must be an ABSOLUTE URL that respects
    the catalog's mount base path (a root-relative one breaks behind a
    path-prefix proxy / some readers). A non-default ``opds_base_path`` yields
    an absolute template carrying that base, and it round-trips."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(opds_settings(cfg, opds_base_path="/comics/opds"))
    with TestClient(app) as client:
        resp = client.get("/comics/opds/opensearch.xml")
        assert resp.status_code == 200
        desc = ET.fromstring(resp.text)
        (url_el,) = desc.findall(f"{OS}Url")
        template = url_el.get("template")
        assert template == "http://testserver/comics/opds/search?q={searchTerms}"

        # The absolute template still reaches the (empty-but-valid) search feed.
        feed_url = template.replace("{searchTerms}", "anything")
        follow = client.get(feed_url)
        assert follow.status_code == 200
        assert follow.headers["content-type"].startswith("application/atom+xml")


@pytest.mark.req("FRG-OPDS-007")
def test_descriptor_and_templated_search_round_trip(client, tmp_path):
    """rel=search -> valid opensearchdescription+xml -> template substitution
    -> matching series as navigation entries into their acquisition feeds."""
    data = _seed(client, tmp_path, [simple_series("Saga", cv_volume_id=1)])
    series_id = data["series"][0]["id"]

    # 1. The root feed advertises the search descriptor.
    root = ET.fromstring(client.get("/opds").text)
    search_links = [
        el for el in root.findall(f"{ATOM}link") if el.get("rel") == "search"
    ]
    assert len(search_links) == 1
    assert search_links[0].get("type") == OS_DESC_TYPE
    descriptor_url = search_links[0].get("href")
    assert descriptor_url == "/opds/opensearch.xml"

    # 2. The descriptor is a valid OpenSearch description document.
    resp = client.get(descriptor_url)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(OS_DESC_TYPE)
    desc = ET.fromstring(resp.text)  # well-formed
    assert desc.tag == f"{OS}OpenSearchDescription"
    (url_el,) = desc.findall(f"{OS}Url")
    template = url_el.get("template")
    # The template is ABSOLUTE (gate fix): a root-relative one breaks behind a
    # path-prefix proxy and some readers reject it. Built from the request base
    # URL joined with the catalog's own mount.
    assert template == "http://testserver/opds/search?q={searchTerms}"

    # 3. Substituting a term into the template reaches the search feed.
    feed_url = template.replace("{searchTerms}", "saga")
    resp = client.get(feed_url)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/atom+xml")
    feed = ET.fromstring(resp.text)
    (entry,) = feed.findall(f"{ATOM}entry")
    assert entry.find(f"{ATOM}title").text == "Saga"
    # Navigation entry INTO the series' acquisition feed — same shape as the
    # All Series shelf, so a reader can walk straight to the downloads.
    (link,) = entry.findall(f"{ATOM}link")
    assert link.get("href") == f"/opds/series/{series_id}"
    assert link.get("type") == ACQ_KIND
    assert client.get(link.get("href")).status_code == 200


@pytest.mark.req("FRG-OPDS-007")
def test_matching_is_case_folded_containment_over_title_and_aliases(client, tmp_path):
    data = _seed(
        client,
        tmp_path,
        [
            simple_series("Spider-Man", cv_volume_id=1, n_issues=0),
            simple_series("Paper Girls", cv_volume_id=2, n_issues=0),
        ],
    )
    spidey = data["series"][0]["id"]
    paper = data["series"][1]["id"]

    # Case, punctuation, and unicode-dash variants all fold to the same key.
    for q in ("spider man", "SPIDER-MAN", "Spider–Man", "spider"):
        assert _entry_hrefs(_search(client, q)) == [f"/opds/series/{spidey}"], q

    # Containment: a fragment of the title matches too.
    assert _entry_hrefs(_search(client, "girls")) == [f"/opds/series/{paper}"]

    # Aliases match with the same folding (the alias-mapping search requirement alias surface).
    client.portal.call(_set_aliases, client.app, paper, ["Papergirls Deluxe"])
    assert _entry_hrefs(_search(client, "PAPERGIRLS")) == [f"/opds/series/{paper}"]

    # No match -> empty but VALID feed with zeroed OpenSearch totals.
    empty = _search(client, "nonexistent series title")
    assert empty.findall(f"{ATOM}entry") == []
    assert empty.find(f"{OS}totalResults").text == "0"

    # An effectively-empty term (whitespace/punctuation only) is also an
    # empty valid feed, never an error.
    assert _search(client, "  ").findall(f"{ATOM}entry") == []
    assert _search(client, "").findall(f"{ATOM}entry") == []


@pytest.mark.req("FRG-OPDS-007")
def test_search_pagination_preserves_the_query(client, tmp_path):
    spec = [
        simple_series(f"Hellboy Volume {i}", cv_volume_id=i, n_issues=0)
        for i in range(1, 8)
    ]
    _seed(client, tmp_path, spec)

    feed = _search(client, "hellboy", page=2, count=3)
    assert feed.find(f"{OS}totalResults").text == "7"
    assert len(feed.findall(f"{ATOM}entry")) == 3
    by_rel = {
        el.get("rel"): el.get("href")
        for el in feed.findall(f"{ATOM}link")
        if el.get("rel") in {"first", "last", "next", "previous", "self"}
    }
    for rel, href in by_rel.items():
        assert href.split("?")[0] == "/opds/search", f"{rel} -> {href}"
        assert "q=hellboy" in href, f"{rel} dropped the query: {href}"
    assert "page=3" in by_rel["next"]
    assert "page=1" in by_rel["previous"]

    # Following the next link really serves the next page of the SAME search.
    page3 = ET.fromstring(client.get(by_rel["next"]).text)
    assert len(page3.findall(f"{ATOM}entry")) == 1  # 7 matches / 3 per page
