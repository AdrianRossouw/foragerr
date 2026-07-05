"""Offset pagination walk: total cross-check, partial-failure complete=False,
hard page cap (FRG-META-004)."""

from __future__ import annotations

import httpx
import pytest

from cv_support import _reset_gate, json_response, make_client  # noqa: F401
from fixtures import issue_payload, issues_envelope


def _page_handler(total: int, page_size: int, *, fail_at_offset: int | None = None,
                  advertised: int | None = None):
    """Serve issue pages; optionally fail one page or advertise a total that
    exceeds the real element count."""
    advertised = total if advertised is None else advertised

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))
        if fail_at_offset is not None and offset == fail_at_offset:
            return httpx.Response(503)
        end = min(offset + page_size, total)
        issues = [
            issue_payload(id=1000 + i, issue_number=str(i + 1))
            for i in range(offset, end)
        ]
        return json_response(
            issues_envelope(issues, total=advertised, offset=offset, limit=page_size)
        )

    return handler


@pytest.mark.req("FRG-META-004")
async def test_offset_walk_assembles_all_pages(tmp_path):
    client, transport = make_client(
        tmp_path,
        _page_handler(total=5, page_size=2),
        comicvine_page_size=2,
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        page = await client.get_issues(18166)
    assert page.complete is True
    assert page.truncated is False
    assert page.total_results == 5
    assert len(page.items) == 5
    assert [i.issue_number for i in page.items] == ["1", "2", "3", "4", "5"]
    # offsets walked 0,2,4
    offsets = [int(r.url.params["offset"]) for r in transport.requests]
    assert offsets == [0, 2, 4]


@pytest.mark.req("FRG-META-004")
async def test_mid_walk_failure_returns_partial_with_complete_false(tmp_path):
    client, _ = make_client(
        tmp_path,
        _page_handler(total=6, page_size=2, fail_at_offset=4),
        comicvine_page_size=2,
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        page = await client.get_issues(18166)
    assert page.complete is False, "partial fetch must flag incompleteness"
    assert len(page.items) == 4  # pages at offset 0 and 2 survived
    assert [i.issue_number for i in page.items] == ["1", "2", "3", "4"]


@pytest.mark.req("FRG-META-004")
async def test_hard_page_cap_bounds_the_walk(tmp_path):
    client, transport = make_client(
        tmp_path,
        _page_handler(total=100, page_size=2),
        comicvine_page_size=2,
        comicvine_max_pages=2,
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        page = await client.get_issues(18166)
    assert len(transport.requests) == 2  # never exceeds the cap
    assert page.truncated is True
    assert page.complete is False
    assert len(page.items) == 4


@pytest.mark.req("FRG-META-004")
async def test_fewer_than_advertised_marks_incomplete(tmp_path):
    # advertises 10 total but only 4 issues actually exist
    client, _ = make_client(
        tmp_path,
        _page_handler(total=4, page_size=2, advertised=10),
        comicvine_page_size=2,
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        page = await client.get_issues(18166)
    assert page.total_results == 10
    assert len(page.items) == 4
    assert page.complete is False
