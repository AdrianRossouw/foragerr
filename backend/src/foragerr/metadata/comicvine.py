"""The typed async ComicVine client (FRG-META-001..008).

A thin, hardened client over the shared outbound factory
(:class:`foragerr.http.HttpClientFactory`) — the ONLY way ComicVine is reached.
Every request:

* is built on the factory's ``external`` profile (SSRF egress policy, TLS
  verify-always, bounded timeouts, byte cap, bounded redirect walk);
* targets base ``https://comicvine.gamespot.com/api`` with ``format=json`` and
  a per-endpoint ``field_list`` to minimise the payload;
* carries an honest ``User-Agent: foragerr/<version>`` and the API key as a
  query parameter (a ``SecretStr`` value; the factory + logging filter redact
  any ``api_key``-shaped parameter from logs — the key is never logged);
* passes through the process-global rate gate (:mod:`.ratelimit`) so all CV
  traffic, covers included, is serialized to the configured min-interval.

Distinct upstream conditions raise distinct typed errors from :mod:`.errors`;
raw ``httpx`` internals never leak (the static-guard forbids importing httpx
here, so transport failures are caught broadly and wrapped as
:class:`ComicVineUnavailable`).
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any, Callable, Mapping, Sequence

from foragerr.db.migrations import app_version
from foragerr.http import HttpClientFactory, OutboundHttpError, parse_retry_after
from foragerr.metadata.errors import (
    ComicVineAuthError,
    ComicVineBudgetExhausted,
    ComicVineError,
    ComicVineMalformedResponse,
    ComicVineRateLimited,
    ComicVineUnavailable,
)
from foragerr.metadata.credits import map_person_credits
from foragerr.metadata.mapping import map_issue, map_volume, map_volume_stubs
from foragerr.metadata.models import (
    CreditRecord,
    IssueRecord,
    Page,
    SearchResult,
    SeriesCandidate,
    SeriesRecord,
    SuggestResult,
    VolumeStub,
)
from foragerr.metadata.ratelimit import effective_budget, effective_interval, gate
from foragerr.metadata.search import plausibility

logger = logging.getLogger("foragerr.metadata.comicvine")

#: ComicVine API base — TLS-verified, JSON-only; never XML (RISK-024/035).
DEFAULT_BASE = "https://comicvine.gamespot.com/api"

#: Per-endpoint field lists (minimise payload; request only what we map).
VOLUME_FIELDS = (
    "id,name,publisher,imprint,start_year,count_of_issues,aliases,description,"
    "site_detail_url,first_issue,image,issues,date_last_updated"
)
SEARCH_VOLUME_FIELDS = (
    "id,name,publisher,imprint,start_year,count_of_issues,aliases,description,"
    "site_detail_url,first_issue,image"
)
ISSUE_FIELDS = "id,name,issue_number,cover_date,store_date,image,volume,person_credits"

#: Minimal field list for the per-issue credit detail fetch (FRG-CRTR-001).
#: ComicVine serves ``person_credits`` only on the issue DETAIL endpoint
#: (``issue/4000-{id}/``) — the list endpoint returns null regardless of
#: ``field_list`` (verified live 2026-07-11) — so this is the credit source.
ISSUE_CREDITS_FIELDS = "id,person_credits"

#: Field list for the person-detail bibliography probe (FRG-CRTR-005). The
#: person endpoint (``person/4040-{id}/``, type prefix 4040 = PERSON, verified
#: live 2026-07-11 — the real API 102s a wrong prefix) serves ``volume_credits``
#: as STUBS (id + name only); the full rows come from a batched volumes hydration.
PERSON_VOLUMES_FIELDS = "id,name,volume_credits"

#: Max volume ids per batched ``volumes/?filter=id:a|b|c`` hydration request
#: (FRG-CRTR-005). CV's per-request result limit is 100, so one request per chunk
#: (``limit=len(chunk)``) returns every matching row in a single page — keeping
#: an upstream failure a raised typed error rather than a silently-partial walk.
VOLUMES_FILTER_CHUNK = 100

#: JSON-response byte cap (lower than the factory ceiling; ample per page).
JSON_MAX_BYTES = 16_000_000

#: Result cap for :meth:`ComicVineClient.suggest_series` (FRG-API-017) — a
#: fixed, small first-page size for as-you-type suggestion, independent of
#: the configured ``comicvine_page_size`` (which sizes the full-walk pages).
SUGGEST_LIMIT = 10

#: Body markers that identify a ComicVine ban / abnormal-traffic HTML page.
_BAN_MARKERS = (
    "abnormal traffic",
    "too many requests",
    "rate limit",
    "request could not be satisfied",
)


def _budget_bucket(path: str) -> str:
    """Classify a request path into its ComicVine budget bucket (FRG-META-016).

    The bucket is the first, normalized URL path segment — the granularity
    ComicVine's own 200/hour limit uses (per resource path). Any trailing
    id/suffix is dropped: ``"volume/4050-123/"`` → ``"volume"``, ``"issues/"`` →
    ``"issues"``, ``"issue/4000-9/"`` → ``"issue"``. No table to maintain.
    """
    return path.strip("/").split("/", 1)[0] or "?"


def split_csv(value: str) -> list[str]:
    """Split a comma-separated settings string into trimmed, non-empty items."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _name_filter(term: str) -> str:
    """Neutralise CV ``filter`` metacharacters in a raw search term so it
    cannot inject additional filter fields (``,`` separates fields, ``:``
    separates field:value) — shared by :meth:`ComicVineClient.search_series`
    and :meth:`ComicVineClient.suggest_series`."""
    return term.replace(",", " ").replace(":", " ").strip()


@lru_cache(maxsize=1)
def user_agent() -> str:
    """The honest ``foragerr/<version>`` User-Agent (resolved once)."""
    return f"foragerr/{app_version()}"


class ComicVineClient:
    """Typed async ComicVine client bound to one outbound ``external`` client.

    Construct with the loaded settings and the shared HTTP factory. Usable as
    an async context manager; otherwise call :meth:`aclose`.
    """

    def __init__(
        self,
        settings,
        factory: HttpClientFactory,
        *,
        base: str | None = None,
    ) -> None:
        self._api_key = settings.comicvine_api_key.get_secret_value()
        self._client = factory.external()
        # Precedence: an explicit ``base=`` (tests) > the ``comicvine_base_url``
        # setting (defaults to the real API, only overridden by the e2e compose
        # harness to point at the fixture ComicVine) > the module default.
        resolved_base = base or getattr(settings, "comicvine_base_url", "") or DEFAULT_BASE
        self._base = resolved_base.rstrip("/")
        self._interval = effective_interval(settings)
        self._budget = effective_budget(settings)
        self._page_size = settings.comicvine_page_size
        self._max_pages = settings.comicvine_max_pages
        self._search_cap = settings.comicvine_search_result_cap
        self._ignored_publishers = frozenset(
            p.casefold() for p in split_csv(settings.comicvine_ignored_publishers)
        )

    # -- public API ---------------------------------------------------------

    async def get_volume(self, volume_id: int) -> SeriesRecord:
        """Fetch one volume's detail and map it to a series record."""
        data = await self._request(
            f"volume/4050-{int(volume_id)}/", {"field_list": VOLUME_FIELDS}
        )
        results = data.get("results")
        if not isinstance(results, dict):
            raise ComicVineMalformedResponse(
                "comicvine volume response missing a results object"
            )
        return map_volume(results)

    async def get_issues(self, volume_id: int) -> Page[IssueRecord]:
        """Page through every issue of a volume (offset walk, partial-tolerant).

        The returned :class:`Page` carries the ``complete`` flag reconciliation
        depends on: ``False`` means the fetch was partial and absent-issue
        deletions must be skipped (FRG-META-004/008).
        """
        base_params = {
            "field_list": ISSUE_FIELDS,
            "filter": f"volume:{int(volume_id)}",
            "sort": "cover_date:asc",
        }
        return await self._paginate("issues/", base_params, map_issue)

    async def get_issue_credits(self, issue_id: int) -> tuple[CreditRecord, ...]:
        """Fetch ONE issue's per-issue person credits from the detail endpoint.

        ComicVine serves ``person_credits`` only on ``issue/4000-{id}/`` (the
        list endpoint returns null — verified live 2026-07-11), so this
        per-issue detail fetch is the sole credit source (FRG-CRTR-001). Like
        every other call it passes through the process-global rate gate, so a
        refresh's bounded fan-out of these fetches is automatically serialized
        to the configured min-interval. The result is mapped/sanitized exactly
        as the opportunistic list path would map it (:func:`map_person_credits`
        — total by contract, empty on absent/malformed credits, never raising);
        a transport/HTTP/malformed failure raises the usual typed
        :class:`~foragerr.metadata.errors.ComicVineError`, which the refresh
        fetch phase degrades to retry-later.
        """
        data = await self._request(
            f"issue/4000-{int(issue_id)}/", {"field_list": ISSUE_CREDITS_FIELDS}
        )
        results = data.get("results")
        if not isinstance(results, dict):
            raise ComicVineMalformedResponse(
                "comicvine issue response missing a results object"
            )
        return map_person_credits(results.get("person_credits"))

    async def get_person_volumes(self, cv_person_id: int) -> tuple[VolumeStub, ...]:
        """Fetch a person's credited-volume STUBS from the person detail endpoint.

        Hits ``person/4040-{id}/`` (type prefix 4040 = PERSON — the real API 102s
        a wrong prefix) with a minimal ``id,name,volume_credits`` field list and
        maps ``volume_credits`` to typed :class:`VolumeStub`s (id + sanitized name
        only — the batched hydration fills the rest, FRG-CRTR-005). Like the credit
        mapper the stub mapping is total: an absent/empty/malformed
        ``volume_credits`` yields ``()`` and never raises. A missing ``results``
        object is a genuine malformed response and raises, exactly as
        :meth:`get_issue_credits` does; transport/HTTP failures raise the usual
        typed :class:`~foragerr.metadata.errors.ComicVineError`.
        """
        data = await self._request(
            f"person/4040-{int(cv_person_id)}/", {"field_list": PERSON_VOLUMES_FIELDS}
        )
        results = data.get("results")
        if not isinstance(results, dict):
            raise ComicVineMalformedResponse(
                "comicvine person response missing a results object"
            )
        return map_volume_stubs(results.get("volume_credits"))

    async def get_volumes_by_ids(
        self, ids: Sequence[int]
    ) -> tuple[SeriesRecord, ...]:
        """Batch-hydrate full volume records by id (FRG-CRTR-005).

        Queries ``volumes/?filter=id:a|b|c`` in chunks of at most
        :data:`VOLUMES_FILTER_CHUNK` ids (deduplicated, order preserved), reusing
        :data:`SEARCH_VOLUME_FIELDS` + :func:`map_volume` so each row carries the
        publisher/start_year/count_of_issues the stubs lack. ``limit=len(chunk)``
        keeps every chunk a single page, so an upstream failure PROPAGATES as a
        typed error (the caller — the bibliography fetch — must preserve its cache
        on failure, not proceed on a silently-partial result) rather than being
        degraded to a partial walk the way :meth:`_paginate` does. Every request
        rides the shared rate gate. An empty ``ids`` performs no request.
        """
        unique = list(dict.fromkeys(int(i) for i in ids))
        out: list[SeriesRecord] = []
        for start in range(0, len(unique), VOLUMES_FILTER_CHUNK):
            chunk = unique[start : start + VOLUMES_FILTER_CHUNK]
            filter_value = "id:" + "|".join(str(i) for i in chunk)
            data = await self._request(
                "volumes/",
                {
                    "field_list": SEARCH_VOLUME_FIELDS,
                    "filter": filter_value,
                    "limit": len(chunk),
                },
            )
            results = data.get("results")
            if not isinstance(results, list):
                raise ComicVineMalformedResponse(
                    "comicvine volumes filter response missing a results list"
                )
            for raw in results:
                if isinstance(raw, dict):
                    out.append(map_volume(raw))
        return tuple(out)

    async def search_series(
        self, term: str, *, target_issue: str | int | None = None
    ) -> SearchResult:
        """Search volumes by name; return bounded, plausibility-annotated
        candidates with ignored-publisher volumes removed (FRG-META-007)."""
        query = term.strip()
        filter_value = _name_filter(query)
        base_params = {
            "field_list": SEARCH_VOLUME_FIELDS,
            "filter": f"name:{filter_value}",
            "sort": "name:asc",
        }
        page = await self._paginate(
            "volumes/", base_params, map_volume, cap_items=self._search_cap
        )
        candidates: list[SeriesCandidate] = []
        for record in page.items:
            publisher = (record.publisher or "").casefold()
            if publisher and publisher in self._ignored_publishers:
                continue
            candidates.append(
                SeriesCandidate(
                    series=record,
                    plausibility=plausibility(
                        query, record, target_issue=target_issue
                    ),
                )
            )
        return SearchResult(
            candidates=tuple(candidates),
            total_results=page.total_results,
            truncated=page.truncated,
            complete=page.complete,
        )

    async def suggest_series(self, term: str) -> SuggestResult:
        """Bounded, single-page volume search for as-you-type suggestion
        (FRG-API-017) — a cheap accelerator over :meth:`search_series`.

        Fetches ONLY the first page (offset 0, ``limit=SUGGEST_LIMIT``) via
        one direct :meth:`_request` call and NEVER loops through
        :meth:`_paginate`'s walk to ``_max_pages`` — this is the load-bearing
        "never the full pagination walk" guarantee. Reuses the exact same
        filter-metacharacter neutralisation as :meth:`search_series` and the
        same ignored-publisher drop, but skips plausibility scoring (no query
        year/target-issue analysis) to keep the call cheap: candidates carry
        only the raw mapped fields (name, start year, publisher, issue count,
        description, image, cv_volume_id).

        A ComicVine auth failure propagates unchanged (the same carve-out
        ``_paginate`` documents: a credential failure cannot be distinguished
        from an empty search if swallowed). Any OTHER upstream failure on
        this single page degrades the result to ``complete=False`` with no
        candidates, rather than raising — there is only one page to lose.
        """
        query = term.strip()
        filter_value = _name_filter(query)
        params = {
            "field_list": SEARCH_VOLUME_FIELDS,
            "filter": f"name:{filter_value}",
            "sort": "name:asc",
            "offset": 0,
            "limit": SUGGEST_LIMIT,
        }
        try:
            data = await self._request("volumes/", params)
        except ComicVineAuthError:
            raise
        except ComicVineBudgetExhausted:
            # Budget carve-out (FRG-META-016): propagate so the suggest route
            # surfaces an honest "resumes in ..." message rather than silently
            # degrading to an empty result (mirrors the auth carve-out above).
            raise
        except ComicVineError:
            return SuggestResult(candidates=(), complete=False)

        results = data.get("results")
        if not isinstance(results, list):
            return SuggestResult(candidates=(), complete=False)

        candidates: list[SeriesRecord] = []
        for raw in results[:SUGGEST_LIMIT]:
            if not isinstance(raw, dict):
                continue
            record = map_volume(raw)
            publisher = (record.publisher or "").casefold()
            if publisher and publisher in self._ignored_publishers:
                continue
            candidates.append(record)

        return SuggestResult(candidates=tuple(candidates), complete=True)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ComicVineClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # -- pagination ---------------------------------------------------------

    async def _paginate(
        self,
        path: str,
        base_params: Mapping[str, Any],
        mapper: Callable[[dict[str, Any]], Any],
        *,
        cap_items: int | None = None,
    ) -> Page:
        """Offset walk bounded by the hard page cap, cross-checked against
        ``number_of_total_results``, returning partial results with
        ``complete=False`` on any mid-walk failure (FRG-META-004)."""
        items: list[Any] = []
        offset = 0
        total: int | None = None
        complete = True
        truncated = False

        for _ in range(self._max_pages):
            params = {**base_params, "offset": offset, "limit": self._page_size}
            try:
                data = await self._request(path, params)
            except ComicVineAuthError:
                # Auth carve-out (FRG-META-004): an invalid/missing key cannot
                # succeed on a later page, so degrading it to a partial result
                # would make a credential failure indistinguishable from an
                # empty search. Re-raise the typed error to the caller instead.
                # The message is a static string (no api_key interpolated).
                raise
            except ComicVineBudgetExhausted:
                # Budget carve-out (FRG-META-016): a local per-path refusal is
                # not a partial upstream result to degrade — silently returning
                # complete=False would hide the deferral and its resume time.
                # Propagate the typed error so the caller (an interactive lookup)
                # can surface an honest "resumes in ..." message, and a refresh's
                # issue walk fails cleanly to retry via its staleness path.
                raise
            except ComicVineError:
                complete = False  # mid-walk failure: keep what we have
                break
            results = data.get("results")
            if not isinstance(results, list):
                complete = False
                break
            for raw in results:
                if isinstance(raw, dict):
                    items.append(mapper(raw))
            advertised = data.get("number_of_total_results")
            if isinstance(advertised, int):
                total = advertised
            got = len(results)
            offset += got
            if cap_items is not None and len(items) >= cap_items:
                items = items[:cap_items]
                truncated = True
                complete = False
                logger.warning(
                    "comicvine result set truncated to the configured cap %d",
                    cap_items,
                )
                break
            if got == 0:
                break
            if total is not None and offset >= total:
                break
        else:
            # loop exhausted the page cap without a natural stop
            if total is not None and offset < total:
                truncated = True
                complete = False
                logger.warning(
                    "comicvine pagination hit the hard page cap %d "
                    "(advertised %s); result is bounded/incomplete",
                    self._max_pages,
                    total,
                )

        if complete and not truncated and total is not None and len(items) < total:
            logger.warning(
                "comicvine returned %d items but advertised %d; marking incomplete",
                len(items),
                total,
            )
            complete = False

        return Page(
            items=tuple(items),
            complete=complete,
            total_results=total,
            truncated=truncated,
        )

    # -- request pipeline ---------------------------------------------------

    async def _request(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        """One CV request end-to-end: gate -> fetch -> status -> JSON -> CV
        error, returning the decoded JSON object or raising a typed error."""
        full_params = {"api_key": self._api_key, "format": "json", **params}
        result = await self._fetch(path, full_params)
        self._raise_for_status(result)
        data = self._decode(result)
        self._raise_for_cv_error(data)
        return data

    async def _fetch(self, path: str, params: Mapping[str, Any]):
        # The path's budget bucket rides the SAME acquire that enforces velocity
        # spacing (FRG-META-003/016): one gate, one admission, both dimensions —
        # so covers and every other call site are budgeted through the one funnel.
        # A refused admission raises ComicVineBudgetExhausted here, before any
        # wire request, and propagates to the call site as a typed ComicVineError.
        await gate().acquire(
            self._interval, bucket=_budget_bucket(path), budget=self._budget
        )
        url = f"{self._base}/{path}"
        try:
            return await self._client.get(
                url,
                params=params,
                headers={"user-agent": user_agent()},
                max_bytes=JSON_MAX_BYTES,
            )
        except OutboundHttpError as exc:
            # SSRF/oversize/redirect refusal from the factory (already redacted).
            raise ComicVineUnavailable(f"comicvine request refused: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            # httpx timeout/transport errors cannot be named here — importing
            # httpx outside foragerr.http is banned by the static-guard test —
            # so any non-typed failure of the network call is wrapped.
            raise ComicVineUnavailable("comicvine request failed") from exc

    def _raise_for_status(self, result) -> None:
        code = result.status_code
        if code == 200:
            # Success clears the auth-failure health dimension (FRG-META-019)
            # so a corrected key recovers Health without a restart.
            gate().note_auth_ok()
            return
        if code in (401, 403):
            gate().note_auth_failed()
            raise ComicVineAuthError(
                f"comicvine authentication failed (HTTP {code})"
            )
        if code in (420, 429):
            retry_after = parse_retry_after(result.headers)
            gate().note_rate_limited(retry_after)
            raise ComicVineRateLimited(
                f"comicvine rate-limited (HTTP {code})", retry_after=retry_after
            )
        if 500 <= code < 600:
            raise ComicVineUnavailable(f"comicvine server error (HTTP {code})")
        raise ComicVineUnavailable(f"comicvine unexpected status (HTTP {code})")

    def _decode(self, result) -> dict[str, Any]:
        try:
            data = json.loads(result.content)
        except ValueError:
            snippet = result.content[:4096].decode("utf-8", "replace").lower()
            if any(marker in snippet for marker in _BAN_MARKERS):
                gate().note_rate_limited(None)
                raise ComicVineRateLimited(
                    "comicvine returned an abnormal-traffic/ban page"
                ) from None
            raise ComicVineMalformedResponse(
                "comicvine returned a non-JSON body"
            ) from None
        if not isinstance(data, dict):
            raise ComicVineMalformedResponse(
                "comicvine response was not a JSON object"
            )
        return data

    def _raise_for_cv_error(self, data: dict[str, Any]) -> None:
        status = data.get("status_code")
        if status in (1, None):  # 1 = OK; absent when the shape has no envelope
            return
        if status == 100:
            raise ComicVineAuthError(
                "comicvine rejected the API key (status_code 100)"
            )
        raise ComicVineMalformedResponse(
            f"comicvine returned error status_code {status}"
        )
