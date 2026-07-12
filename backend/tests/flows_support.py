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
        #: cv issue id -> person_credits served on the DETAIL endpoint
        #: (``issue/4000-{id}/``) — the real credit source (FRG-CRTR-001). The
        #: real ComicVine returns person_credits: null on the LIST endpoint, so
        #: this fixture mirrors that: credits registered via ``issue(credits=)``
        #: are served on the detail endpoint, NOT the list rows (unless a test
        #: opts in via ``issues(..., list_credits=True)`` to exercise the
        #: opportunistic list-mapping path).
        self._issue_credits: dict[int, list[dict]] = {}
        #: cv issue id -> (HTTP status) for a failing detail fetch.
        self._issue_detail_fail: dict[int, int] = {}
        #: cv person id -> volume_credits STUBS served on the person DETAIL
        #: endpoint (``person/4040-{id}/``) — id+name only, mirroring the real
        #: shape (FRG-CRTR-005). Full rows come from the volumes id-filter route.
        self._person_volume_credits: dict[int, list[dict]] = {}
        #: cv person id -> HTTP status for a failing person detail fetch.
        self._person_fail: dict[int, int] = {}
        #: filter substring that, when present on a ``volumes/?filter=id:...``
        #: request, makes it fail with the given HTTP status (hydration failure).
        self._volumes_filter_fail_status: int | None = None

    def volume(
        self,
        volume_id: int,
        *,
        name: str = "Saga",
        publisher: str | None = "Image",
        start_year: int | None = 2012,
        count_of_issues: int | None = None,
        description: str | None = "A space opera.",
        image_url: str | None = None,
        date_last_updated: str | None = None,
    ) -> "FakeCV":
        vol: dict = {"id": volume_id, "name": name, "start_year": start_year}
        if publisher is not None:
            vol["publisher"] = {"name": publisher}
        if count_of_issues is not None:
            vol["count_of_issues"] = count_of_issues
        if description is not None:
            vol["description"] = description
        if image_url is not None:
            vol["image"] = {"original_url": image_url}
            self._images.add(image_url.split("?")[0])
        if date_last_updated is not None:
            # Served on the volume detail (FRG-META-017): the unchanged-volume
            # refresh short-circuit compares it verbatim against the stored stamp.
            vol["date_last_updated"] = date_last_updated
        self._volumes[volume_id] = vol
        return self

    def person(
        self,
        cv_person_id: int,
        volume_ids: list[int] | None = None,
        *,
        volume_credits: list[dict] | None = None,
        fail_status: int | None = None,
    ) -> "FakeCV":
        """Register a person's ``volume_credits`` STUBS for the person DETAIL
        endpoint (``person/4040-{id}/``) — the real bibliography source shape:
        id+name stubs only, NOT the full rows (FRG-CRTR-005). Pass ``volume_ids``
        for the common case (stub name defaults to ``Volume <id>``), or
        ``volume_credits`` to supply raw stub dicts (e.g. malformed entries).
        ``fail_status`` makes the person detail fetch fail with that HTTP status.
        """
        if fail_status is not None:
            self._person_fail[cv_person_id] = fail_status
        if volume_credits is None:
            volume_credits = [
                {
                    "id": vid,
                    "name": f"Volume {vid}",
                    "api_detail_url": (
                        f"https://comicvine.gamespot.com/api/volume/4050-{vid}/"
                    ),
                    "site_detail_url": f"https://comicvine.gamespot.com/v/4050-{vid}/",
                }
                for vid in (volume_ids or [])
            ]
        self._person_volume_credits[cv_person_id] = volume_credits
        return self

    def fail_volumes_filter(self, status: int = 500) -> "FakeCV":
        """Make every ``volumes/?filter=id:...`` hydration request fail (used to
        exercise the bibliography fetch's cache-preserving failure path)."""
        self._volumes_filter_fail_status = status
        return self

    def issues(
        self,
        volume_id: int,
        issues: list[dict],
        *,
        fail_after_offset: int | None = None,
        fail_status: int = 500,
        list_credits: bool = False,
        detail_fail: dict[int, int] | None = None,
    ) -> "FakeCV":
        """Register a volume's issues; ``fail_after_offset`` makes every page
        at or past that offset fail with ``fail_status`` (500 = a transient
        mid-walk failure the walk degrades on; 401 = an auth rejection the
        walk propagates).

        Per-issue ``person_credits`` supplied via :func:`issue`'s ``credits``
        are split off onto the DETAIL endpoint (``issue/4000-{id}/``) — mirroring
        the real API, whose LIST endpoint returns null credits. Pass
        ``list_credits=True`` to ALSO serve those credits on the list rows (the
        opportunistic-mapping / tripwire path). ``detail_fail`` maps a cv issue
        id to an HTTP status its detail fetch should fail with (retry-later).
        """
        rows: list[dict] = []
        for raw in issues:
            row = dict(raw)
            creds = row.pop("person_credits", None)
            if creds is not None:
                self._issue_credits[row["id"]] = creds
                if list_credits:
                    row["person_credits"] = creds
            rows.append(row)
        self._issues[volume_id] = rows
        if fail_after_offset is not None:
            self._issue_fail_after_offset[volume_id] = (fail_after_offset, fail_status)
        if detail_fail:
            self._issue_detail_fail.update(detail_fail)
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
            if "/issue/4000-" in path:
                # The per-issue credit DETAIL endpoint (FRG-CRTR-001) — the only
                # place the real API serves person_credits. Type prefix 4000 =
                # issue (4050 = volume); the real API 102s a wrong prefix.
                iid = int(path.split("4000-")[1].rstrip("/"))
                fail = self._issue_detail_fail.get(iid)
                if fail is not None:
                    return httpx.Response(fail, content=b"boom")
                return _envelope(
                    {"id": iid, "person_credits": self._issue_credits.get(iid, [])}
                )
            if "/person/4040-" in path:
                # The person DETAIL endpoint (FRG-CRTR-005) — serves volume_credit
                # STUBS. Type prefix 4040 = person (4050 = volume); the real API
                # 102s a wrong prefix.
                pid = int(path.split("4040-")[1].rstrip("/"))
                fail = self._person_fail.get(pid)
                if fail is not None:
                    return httpx.Response(fail, content=b"boom")
                if pid not in self._person_volume_credits:
                    return httpx.Response(404, content=b"not found")
                return _envelope(
                    {
                        "id": pid,
                        "name": f"Person {pid}",
                        "volume_credits": self._person_volume_credits[pid],
                    }
                )
            if path.endswith("/volumes/"):
                if query.get("filter", "").startswith("id:"):
                    return self._volumes_by_ids_response(query)
                return self._search_response(query)
            if path.endswith("/issues/"):
                return self._issues_response(query)
            return httpx.Response(404, content=b"unknown endpoint")

        return _handle

    def _search_response(self, query: dict[str, str]) -> httpx.Response:
        """Answer the plural ``volumes/`` name-filtered search endpoint
        (``search_series``) from the registered volumes: a case-insensitive
        substring match in either direction, first page only."""
        filter_value = query.get("filter", "")
        term = filter_value.split("name:", 1)[1] if "name:" in filter_value else ""
        term = term.strip().casefold()
        offset = int(query.get("offset", "0"))
        matches = [
            vol
            for vol in self._volumes.values()
            if term
            and (
                term in str(vol.get("name", "")).casefold()
                or str(vol.get("name", "")).casefold() in term
            )
        ]
        window = matches if offset == 0 else []
        return _envelope(window, number_of_total_results=len(matches))

    def _volumes_by_ids_response(self, query: dict[str, str]) -> httpx.Response:
        """Answer the batched ``volumes/?filter=id:a|b|c`` hydration endpoint
        (``get_volumes_by_ids``) from the registered FULL volume rows, mirroring
        the real pipe-filter shape (FRG-CRTR-005)."""
        if self._volumes_filter_fail_status is not None:
            return httpx.Response(self._volumes_filter_fail_status, content=b"boom")
        filter_value = query.get("filter", "")
        ids_part = filter_value.split("id:", 1)[1] if "id:" in filter_value else ""
        ids = [int(tok) for tok in ids_part.split("|") if tok.strip().isdigit()]
        rows = [self._volumes[i] for i in ids if i in self._volumes]
        offset = int(query.get("offset", "0"))
        limit = int(query.get("limit", "100"))
        window = rows[offset : offset + limit]
        return _envelope(window, number_of_total_results=len(rows))

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
    credits: list[dict] | None = None,
) -> dict:
    """One CV issue JSON object for :meth:`FakeCV.issues`.

    ``credits`` are CV person-credit objects (``{"id", "name", "role"}``). They
    are NOT embedded in the returned list row — :meth:`FakeCV.issues` splits them
    onto the DETAIL endpoint (``issue/4000-{id}/``), mirroring the real API whose
    LIST endpoint returns null credits; credit ingest (FRG-CRTR-001) is then
    exercised through the real client's detail fetch + mapper. ``credits=[]``
    registers a legitimately creditless issue (detail returns an empty list).
    """
    payload: dict = {"id": cv_issue_id, "issue_number": number}
    if title is not None:
        payload["name"] = title
    if cover_date is not None:
        payload["cover_date"] = cover_date
    if store_date is not None:
        payload["store_date"] = store_date
    if image_url is not None:
        payload["image"] = {"original_url": image_url}
    if credits is not None:
        payload["person_credits"] = credits
    return payload


def credit(cv_person_id: int, name: str, role: str) -> dict:
    """One CV ``person_credits`` object for :func:`issue`'s ``credits`` list."""
    return {"id": cv_person_id, "name": name, "role": role}
