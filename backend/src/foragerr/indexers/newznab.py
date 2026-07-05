"""The Newznab wire client (FRG-IDX-004/005/006/008).

A thin, hardened client over the shared outbound factory's ``external`` profile
(SSRF egress policy, TLS-verify-always, bounded timeouts, byte cap, bounded
redirect walk) — the only way an indexer is reached. Every request:

* passes the per-indexer 2 s spacing gate (:mod:`foragerr.indexers.ratelimit`)
  before going out, including across paging (FRG-IDX-008);
* carries an honest ``foragerr/<version>`` User-Agent and the API key as an
  ``apikey`` query parameter (redacted from logs by the factory + log filter);
* maps HTTP status to the typed failures the back-off ladder consumes
  (auth / limit / unavailable), never a bare transport error.

This module owns the wire only. Query generation is
:mod:`foragerr.indexers.query`; feed parsing is
:mod:`foragerr.indexers.parse`; caps modelling is
:mod:`foragerr.indexers.caps`.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Mapping
from urllib.parse import parse_qsl

from foragerr.db.migrations import app_version
from foragerr.http import HttpClientFactory, OutboundHttpError, parse_retry_after
from foragerr.indexers import ratelimit
from foragerr.indexers.caps import Capabilities, parse_caps
from foragerr.indexers.errors import (
    IndexerAuthError,
    IndexerLimitError,
    IndexerUnavailable,
)
from foragerr.indexers.settings import NewznabSettings

logger = logging.getLogger("foragerr.indexers.newznab")

#: Response byte cap for indexer XML (ample per page, under the factory ceiling).
XML_MAX_BYTES = 8_000_000


@lru_cache(maxsize=1)
def user_agent() -> str:
    """The honest ``foragerr/<version>`` User-Agent (resolved once)."""
    return f"foragerr/{app_version()}"


class NewznabClient:
    """Async Newznab client bound to one indexer's outbound ``external`` client.

    Usable as an async context manager; otherwise call :meth:`aclose`.
    """

    def __init__(
        self,
        settings_model: NewznabSettings,
        factory: HttpClientFactory,
        *,
        indexer_id: int,
        min_interval: float = ratelimit.DEFAULT_MIN_INTERVAL,
    ) -> None:
        base = settings_model.base_url.rstrip("/")
        self._api_url = base if base.endswith("/api") else f"{base}/api"
        self._api_key = settings_model.api_key.get_secret_value()
        self._default_categories = list(settings_model.categories)
        self._additional = _parse_additional(settings_model.additional_parameters)
        self._client = factory.external()
        self._indexer_id = indexer_id
        self._min_interval = min_interval

    @property
    def default_categories(self) -> list[int]:
        return list(self._default_categories)

    async def caps(self) -> Capabilities:
        """Fetch and parse this indexer's ``?t=caps`` response (FRG-IDX-004).

        Raises a typed failure on HTTP/transport/parse error; the caller
        decides whether to degrade to conservative defaults."""
        content = await self._get({"t": "caps"})
        return parse_caps(content)

    async def search(
        self,
        *,
        query: str,
        categories: list[int],
        offset: int = 0,
        limit: int = 100,
        maxage: int | None = None,
    ) -> bytes:
        """One ``t=search`` request; returns the raw XML for the parser.

        HTTP-status failures map to typed failures here; the feed parser maps
        ``<error code>`` documents (FRG-IDX-006)."""
        params: dict[str, Any] = {
            "t": "search",
            "q": query,
            "cat": ",".join(str(c) for c in categories),
            "offset": offset,
            "limit": limit,
        }
        if maxage is not None:
            params["maxage"] = maxage  # usenet retention (FRG-IDX-009)
        return await self._get(params)

    async def _get(self, params: Mapping[str, Any]) -> bytes:
        # Per-indexer 2 s spacing gate — applied to EVERY request incl. paging.
        await ratelimit.acquire(self._indexer_id, self._min_interval)
        full = {
            **self._additional,
            "apikey": self._api_key,
            "o": "xml",
            **params,
        }
        try:
            result = await self._client.get(
                self._api_url,
                params=full,
                headers={"user-agent": user_agent()},
                max_bytes=XML_MAX_BYTES,
            )
        except OutboundHttpError as exc:
            raise IndexerUnavailable(f"indexer request refused: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — httpx types can't be named here
            raise IndexerUnavailable("indexer request failed") from exc
        self._raise_for_status(result)
        return result.content

    def _raise_for_status(self, result) -> None:
        code = result.status_code
        if code == 200:
            return
        if code in (401, 403):
            raise IndexerAuthError(f"indexer authentication failed (HTTP {code})")
        if code == 429:
            retry_after = parse_retry_after(result.headers)
            raise IndexerLimitError(
                f"indexer rate-limited (HTTP {code})", retry_after=retry_after
            )
        if 500 <= code < 600:
            raise IndexerUnavailable(f"indexer server error (HTTP {code})")
        raise IndexerUnavailable(f"indexer unexpected status (HTTP {code})")

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "NewznabClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


def _parse_additional(value: str | None) -> dict[str, str]:
    """Parse the optional ``additional_parameters`` string (``k=v&k2=v2``)
    into a params dict, tolerating a leading ``&`` or ``?``."""
    if not value:
        return {}
    return dict(parse_qsl(value.lstrip("?&"), keep_blank_values=False))
