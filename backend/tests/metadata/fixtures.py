"""Synthetic but real-shaped ComicVine JSON payloads for the mapping/client
tests, including hostile cases (embedded HTML/script, non-ASCII, null fields).
"""

from __future__ import annotations

from typing import Any

# A hostile description: script tag (body must be dropped), nested inline tags,
# an encoded entity, and path-separator/quote characters in prose.
HOSTILE_DESCRIPTION = (
    "<p>Epic <b>space</b> opera &amp; family saga.</p>"
    "<script>alert('xss')</script>"
    "<p>See ../../etc/passwd &lt;not a tag&gt; \"quoted\".</p>"
)


def volume_payload(**overrides: Any) -> dict[str, Any]:
    """A well-formed CV volume detail ``results`` object.

    Note the ``issues`` array has 4 elements while ``count_of_issues`` is 3, so
    the element-count-wins rule (FRG-META-005) is exercised.
    """
    results: dict[str, Any] = {
        "id": 18166,
        "name": "Saga",
        "publisher": {"id": 1, "name": "Image Comics"},
        "imprint": None,
        "start_year": "2012",
        "count_of_issues": 3,
        "aliases": "Saga Comic\nBKV Saga",
        "description": HOSTILE_DESCRIPTION,
        "site_detail_url": "https://comicvine.gamespot.com/saga/4050-18166/",
        "first_issue": {"id": 348871, "name": "Chapter One", "issue_number": "1"},
        "image": {
            "original_url": "https://comicvine.gamespot.com/a/uploads/original/saga.jpg"
        },
        "issues": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}],
    }
    results.update(overrides)
    return results


def volume_envelope(results: dict[str, Any] | None = None) -> dict[str, Any]:
    """Wrap a volume ``results`` object in the CV single-resource envelope."""
    return {
        "error": "OK",
        "limit": 1,
        "offset": 0,
        "number_of_page_results": 1,
        "number_of_total_results": 1,
        "status_code": 1,
        "results": results if results is not None else volume_payload(),
    }


def issue_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 348871,
        "name": "Chapter One",
        "issue_number": "1",
        "cover_date": "2012-03-14",
        "store_date": "2012-03-14",
        "image": {
            "original_url": "https://comicvine.gamespot.com/a/uploads/original/1.jpg"
        },
        "volume": {"id": 18166, "name": "Saga"},
    }
    base.update(overrides)
    return base


def issues_envelope(
    issues: list[dict[str, Any]], *, total: int, offset: int = 0, limit: int = 100
) -> dict[str, Any]:
    """Wrap an issues page in the CV list envelope."""
    return {
        "error": "OK",
        "limit": limit,
        "offset": offset,
        "number_of_page_results": len(issues),
        "number_of_total_results": total,
        "status_code": 1,
        "results": issues,
    }


def search_envelope(
    volumes: list[dict[str, Any]], *, total: int, offset: int = 0, limit: int = 100
) -> dict[str, Any]:
    """Wrap a volumes-search page (list of volume objects) in the CV envelope."""
    return {
        "error": "OK",
        "limit": limit,
        "offset": offset,
        "number_of_page_results": len(volumes),
        "number_of_total_results": total,
        "status_code": 1,
        "results": volumes,
    }


# A ComicVine "Abnormal Traffic" ban page — HTML, not JSON.
BAN_PAGE_HTML = (
    "<html><head><title>ComicVine</title></head><body>"
    "<h1>Abnormal Traffic Detected</h1>"
    "<p>Your request could not be satisfied. Please try again later.</p>"
    "</body></html>"
)
