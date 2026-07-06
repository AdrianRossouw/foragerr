"""Shared helpers for the library-flows tests.

Builds a real :class:`~foragerr.metadata.ComicVineClient` over an injected
``RecordingTransport`` + ``StubResolver`` (no DNS, no network), driven by a
small in-memory ``FakeCV`` that answers ``get_volume`` / ``get_issues`` in the
ComicVine JSON envelope shape. Reusing the real client exercises the mapping,
pagination and rate-gate code paths exactly as production does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit

import httpx

from foragerr.config import Settings
from foragerr.http import HttpClientFactory
from foragerr.metadata import ratelimit

from http_support import PUBLIC_V4, RecordingTransport, StubResolver, make_settings

CV_HOST = "comicvine.gamespot.com"


def reset_gate() -> None:
    ratelimit.reset_gate()


def flows_settings(config_dir: Path, **overrides: object) -> Settings:
    """Settings for a flows test: fast CV interval, temp config dir."""
    overrides.setdefault("comicvine_api_key", "CV-SECRET-KEY-abc123")
    overrides.setdefault("comicvine_min_interval_seconds", 0.25)
    return make_settings(config_dir, **overrides)


def build_factory(
    settings: Settings, handler: Callable[[httpx.Request], httpx.Response]
) -> HttpClientFactory:
    """A factory whose ``external()`` client is wired to ``handler`` + stub DNS."""
    resolver = StubResolver({CV_HOST: [PUBLIC_V4]})
    transport = RecordingTransport(handler)
    return HttpClientFactory(settings, resolver=resolver, transport=transport)


def _envelope(results: object, **extra: object) -> httpx.Response:
    payload = {"status_code": 1, "results": results, **extra}
    return httpx.Response(200, content=json.dumps(payload).encode())


class FakeCV:
    """An in-memory ComicVine double producing an httpx handler."""

    def __init__(self) -> None:
        self._volumes: dict[int, dict] = {}
        self._issues: dict[int, list[dict]] = {}
        #: volume id -> (offset threshold, HTTP status) for a mid-walk failure.
        self._issue_fail_after_offset: dict[int, tuple[int, int]] = {}
        self._images: set[str] = set()

    def volume(
        self,
        volume_id: int,
        *,
        name: str = "Saga",
        publisher: str | None = "Image",
        start_year: int | None = 2012,
        description: str | None = "A space opera.",
        image_url: str | None = None,
    ) -> "FakeCV":
        vol: dict = {"id": volume_id, "name": name, "start_year": start_year}
        if publisher is not None:
            vol["publisher"] = {"name": publisher}
        if description is not None:
            vol["description"] = description
        if image_url is not None:
            vol["image"] = {"original_url": image_url}
            self._images.add(image_url.split("?")[0])
        self._volumes[volume_id] = vol
        return self

    def issues(
        self,
        volume_id: int,
        issues: list[dict],
        *,
        fail_after_offset: int | None = None,
        fail_status: int = 500,
    ) -> "FakeCV":
        """Register a volume's issues; ``fail_after_offset`` makes every page
        at or past that offset fail with ``fail_status`` (500 = a transient
        mid-walk failure the walk degrades on; 401 = an auth rejection the
        walk propagates)."""
        self._issues[volume_id] = issues
        if fail_after_offset is not None:
            self._issue_fail_after_offset[volume_id] = (fail_after_offset, fail_status)
        return self

    # -- handler -----------------------------------------------------------

    def handler(self) -> Callable[[httpx.Request], httpx.Response]:
        def _handle(request: httpx.Request) -> httpx.Response:
            parts = urlsplit(str(request.url))
            query = {k: v[0] for k, v in parse_qs(parts.query).items()}
            path = parts.path
            if f"{parts.scheme}://{parts.netloc}{path}" in self._images:
                return httpx.Response(200, content=b"\xff\xd8\xff\xe0JPEGBYTES")
            if "/volume/4050-" in path:
                vid = int(path.split("4050-")[1].rstrip("/"))
                vol = self._volumes.get(vid)
                if vol is None:
                    return httpx.Response(404, content=b"not found")
                return _envelope(vol)
            if path.endswith("/issues/"):
                return self._issues_response(query)
            return httpx.Response(404, content=b"unknown endpoint")

        return _handle

    def _issues_response(self, query: dict[str, str]) -> httpx.Response:
        filter_value = query.get("filter", "")
        vid = int(filter_value.split("volume:")[1]) if "volume:" in filter_value else 0
        all_issues = self._issues.get(vid, [])
        offset = int(query.get("offset", "0"))
        limit = int(query.get("limit", "100"))
        fail = self._issue_fail_after_offset.get(vid)
        if fail is not None and offset >= fail[0]:
            return httpx.Response(fail[1], content=b"boom")
        window = all_issues[offset : offset + limit]
        return _envelope(window, number_of_total_results=len(all_issues))


def issue(
    cv_issue_id: int,
    number: str | None,
    *,
    title: str | None = None,
    cover_date: str | None = None,
    store_date: str | None = None,
    image_url: str | None = None,
) -> dict:
    """One CV issue JSON object for :meth:`FakeCV.issues`."""
    payload: dict = {"id": cv_issue_id, "issue_number": number}
    if title is not None:
        payload["name"] = title
    if cover_date is not None:
        payload["cover_date"] = cover_date
    if store_date is not None:
        payload["store_date"] = store_date
    if image_url is not None:
        payload["image"] = {"original_url": image_url}
    return payload
