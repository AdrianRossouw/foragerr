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
from typing import Any, Callable, Mapping

from foragerr.db.migrations import app_version
from foragerr.http import HttpClientFactory, OutboundHttpError, parse_retry_after
from foragerr.metadata.errors import (
    ComicVineAuthError,
    ComicVineError,
    ComicVineMalformedResponse,
    ComicVineRateLimited,
    ComicVineUnavailable,
)
from foragerr.metadata.mapping import map_issue, map_volume
from foragerr.metadata.models import IssueRecord, Page, SearchResult, SeriesCandidate, SeriesRecord
from foragerr.metadata.ratelimit import effective_interval, gate
from foragerr.metadata.search import plausibility

logger = logging.getLogger("foragerr.metadata.comicvine")

#: ComicVine API base — TLS-verified, JSON-only; never XML (RISK-024/035).
DEFAULT_BASE = "https://comicvine.gamespot.com/api"

#: Per-endpoint field lists (minimise payload; request only what we map).
VOLUME_FIELDS = (
    "id,name,publisher,imprint,start_year,count_of_issues,aliases,description,"
    "site_detail_url,first_issue,image,issues"
)
SEARCH_VOLUME_FIELDS = (
    "id,name,publisher,imprint,start_year,count_of_issues,aliases,description,"
    "site_detail_url,first_issue,image"
)
ISSUE_FIELDS = "id,name,issue_number,cover_date,store_date,image,volume"

#: JSON-response byte cap (lower than the factory ceiling; ample per page).
JSON_MAX_BYTES = 16_000_000

#: Body markers that identify a ComicVine ban / abnormal-traffic HTML page.
_BAN_MARKERS = (
    "abnormal traffic",
    "too many requests",
    "rate limit",
    "request could not be satisfied",
)


def split_csv(value: str) -> list[str]:
    """Split a comma-separated settings string into trimmed, non-empty items."""
    return [item.strip() for item in value.split(",") if item.strip()]


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

    async def search_series(
        self, term: str, *, target_issue: str | int | None = None
    ) -> SearchResult:
        """Search volumes by name; return bounded, plausibility-annotated
        candidates with ignored-publisher volumes removed (FRG-META-007)."""
        query = term.strip()
        # Neutralise CV filter metacharacters so the query cannot inject
        # additional filter fields (`,` separates fields, `:` field:value).
        filter_value = query.replace(",", " ").replace(":", " ").strip()
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
        await gate().acquire(self._interval)
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
            return
        if code in (401, 403):
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
