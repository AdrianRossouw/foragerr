"""The GetComics search provider (FRG-DDL-002/003/006).

Registered as a change-4 search provider (an ``indexers`` row with protocol
``ddl``) so its results compete with, and are explained like, Newznab results in
the ONE shared decision engine — foragerr's deliberate divergence from Mylar,
which stops at its own first filtered match (mylar-ddl §3.7). The provider:

- walks an escalating query ladder (quoted exact → unquoted → name #issue →
  name year), escalating only when a tier yields nothing (bounded, polite);
- follows "older posts" pagination up to a configured depth cap, de-duplicating
  by post URL and skipping weekly-roundup posts;
- runs every HTML parse through :mod:`foragerr.ddl.adapter_v1`, turning a typed
  :class:`~foragerr.ddl.errors.AdapterDrift` into zero results + a provider
  health warning + shared back-off (never a crash, never a mis-parse);
- rate-limits page fetches (≥ interval + jitter, persisted) and self-protects on
  429/503, a Cloudflare challenge, or a connection failure via the shared
  ``PROVIDER_DDL`` back-off ladder.

All emitted records are plain :class:`~foragerr.releases.ReleaseCandidate`s — no
DDL-private quality/ranking notion; the page's quality badge rides as an
attribute for the shared comparator/explanation only.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote_plus

from foragerr.db.base import utcnow
from foragerr.ddl import politeness
from foragerr.ddl.adapter_v1 import ParsedPost, parse_search_page
from foragerr.ddl.errors import AdapterDrift
from foragerr.ddl.settings import GetComicsSettings
from foragerr.ddl.state import resolve_config_dir
from foragerr.http import HttpClientFactory, OutboundHttpError
from foragerr.indexers.errors import IndexerUnavailable
from foragerr.indexers.models import IndexerRow
from foragerr.indexers.query import SearchTarget, clean_query_term
from foragerr.indexers.service import IndexerSearchOutcome
from foragerr.providers.backoff import PROVIDER_DDL, ProviderBackoff
from foragerr.releases import ReleaseCandidate

logger = logging.getLogger("foragerr.ddl.search_provider")

#: GetComics HTML fragments that mark a Cloudflare challenge (FRG-DDL-006).
_CLOUDFLARE_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "checking your browser",
    "attention required",
    "cf-chl",
)

#: HTTP statuses that escalate the back-off ladder (rate-limit / unavailable).
_BACKOFF_STATUSES = frozenset({429, 503})


def _load_settings(row: IndexerRow) -> GetComicsSettings:
    import json

    # NOTE: this bypasses the keystore-decrypting ``indexers.repo.load_settings``.
    # It is SAFE only because ``GetComicsSettings`` carries NO ``SecretStr`` field
    # (nothing to decrypt). If a secret is ever added to it, route this (and the
    # ``ddl.queue._provider_base_url`` sibling) through the decrypting loader — the
    # m6-keystore tripwire test asserts ``GetComicsSettings`` stays secret-free so
    # this bypass cannot be tripped silently.
    return GetComicsSettings.model_validate(json.loads(row.settings))


def build_query_ladder(target: SearchTarget) -> list[tuple[int, str]]:
    """The escalating query ladder for one search target (FRG-DDL-002).

    Tier 0 is the most specific; the caller escalates toward title-only only
    when a tier returns nothing. Year-dependent forms are omitted when the year
    is unknown."""
    name = clean_query_term(target.series_title)
    if not name:
        return []
    issue = (target.issue_number or "").strip()
    year = target.year
    ladder: list[str] = []
    if issue:
        if year:
            ladder.append(f'"{name} #{issue} ({year})"')
            ladder.append(f"{name} #{issue} ({year})")
        ladder.append(f"{name} #{issue}")
        if year:
            ladder.append(f"{name} {year}")
    else:
        if year:
            ladder.append(f'"{name} ({year})"')
            ladder.append(f"{name} {year}")
        ladder.append(name)
    # De-dup while preserving order (a missing year can collapse two forms).
    seen: set[str] = set()
    out: list[tuple[int, str]] = []
    for query in ladder:
        if query not in seen:
            seen.add(query)
            out.append((len(out), query))
    return out


def _search_url(base_url: str, query: str) -> str:
    return f"{base_url}/?s={quote_plus(query)}"


def _is_cloudflare(html: str) -> bool:
    low = html.lower()
    return any(marker in low for marker in _CLOUDFLARE_MARKERS)


def _candidate(post: ParsedPost, row: IndexerRow, tier: int) -> ReleaseCandidate:
    from foragerr.ddl.links import classify_quality

    quality = classify_quality(post.title)
    return ReleaseCandidate(
        guid=post.post_url,  # unique per post; the (indexer_id, guid) grab key
        title=post.title,
        link=post.post_url,  # the DDL client resolves download links from this
        indexer_id=row.id,
        indexer_name=row.name,
        indexer_priority=row.priority,
        query_tier=tier,
        size_bytes=post.size_bytes,
        pub_date=post.pub_date,
        categories=(),
        attributes={
            "source": "ddl",
            "post_url": post.post_url,
            "ddl_quality": str(quality),
        },
    )


class _ProviderBackoffEngaged(Exception):
    """Internal: a fetch outcome that must degrade health + engage back-off."""

    def __init__(self, reason: str, *, fast_forward: bool = False,
                 retry_after: float | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.fast_forward = fast_forward
        self.retry_after = retry_after


async def _fetch_page(
    factory: HttpClientFactory, url: str, hop_check=None
) -> str:
    """Fetch one search page, mapping HTTP/transport faults to back-off.

    ``hop_check`` is the per-provider host allowlist validator (FRG-DDL-012): a
    hostile search-page response cannot steer the GET or its redirects to an
    off-allowlist public host.
    """
    client = factory.external()
    try:
        result = await client.get(url, hop_check=hop_check)
    except OutboundHttpError as exc:
        raise _ProviderBackoffEngaged(f"page fetch refused: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — httpx types can't be named here
        raise _ProviderBackoffEngaged("page fetch failed (connection)") from exc
    finally:
        await client.aclose()
    if result.status_code in _BACKOFF_STATUSES:
        raise _ProviderBackoffEngaged(
            f"HTTP {result.status_code}", fast_forward=True
        )
    if result.status_code != 200:
        raise _ProviderBackoffEngaged(f"HTTP {result.status_code}")
    html = result.content.decode("utf-8", errors="replace")
    if _is_cloudflare(html):
        raise _ProviderBackoffEngaged("Cloudflare challenge", fast_forward=True)
    return html


async def _walk_tier(
    *,
    factory: HttpClientFactory,
    base_url: str,
    query: str,
    tier: int,
    max_pages: int,
    row: IndexerRow,
    seen_urls: set[str],
    config_dir: Path,
    min_interval: float,
    sleep: Callable[[float], Awaitable[None]] | None,
    clock,
    rand,
    hop_check=None,
) -> list[ReleaseCandidate]:
    """Walk one query tier's pages, deduping + skipping roundups."""
    candidates: list[ReleaseCandidate] = []
    url: str | None = _search_url(base_url, query)
    pages = 0
    throttle_kwargs: dict[str, Any] = {"min_interval": min_interval, "clock": clock,
                                       "rand": rand}
    if sleep is not None:
        throttle_kwargs["sleep"] = sleep
    while url is not None and pages < max_pages:
        await politeness.throttle(config_dir, row.id, **throttle_kwargs)
        html = await _fetch_page(factory, url, hop_check)
        page = parse_search_page(html, base_url=base_url)  # may raise AdapterDrift
        for post in page.posts:
            if post.post_url in seen_urls:
                continue
            seen_urls.add(post.post_url)
            if post.is_roundup:
                continue
            candidates.append(_candidate(post, row, tier))
        pages += 1
        url = page.next_page_url
    return candidates


async def search_getcomics(
    row: IndexerRow,
    target: SearchTarget,
    *,
    factory: HttpClientFactory,
    backoff: ProviderBackoff,
    config_dir: Path | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    clock: Callable[[], datetime] = utcnow,
    rand: Callable[[], float] | None = None,
    **_ignored: Any,
) -> IndexerSearchOutcome:
    """Search GetComics for ``target``, feeding the shared engine (FRG-DDL-002).

    Owns its own ``PROVIDER_DDL`` back-off gate (checked at entry, escalated on
    fault) rather than the Newznab ``PROVIDER_INDEXER`` gate — the dispatch in
    :func:`foragerr.indexers.service.search_indexer` routes ``ddl`` rows here
    before that gate. Returns an :class:`IndexerSearchOutcome`; a drift or a
    self-protection fault yields zero candidates + a set ``failure`` (degraded
    health) and engages the shared ladder.
    """
    import random as _random

    outcome = IndexerSearchOutcome(indexer_id=row.id, indexer_name=row.name)
    status = await backoff.status(PROVIDER_DDL, row.id)
    if status.active:
        outcome.backing_off = True
        return outcome

    settings = _load_settings(row)
    ladder = build_query_ladder(target)
    if not ladder:
        return outcome
    cfg_dir = Path(config_dir) if config_dir is not None else resolve_config_dir()
    rand = rand or _random.random
    seen_urls: set[str] = set()
    # Confine every search-page GET + redirect hop to the provider's host
    # allowlist (FRG-DDL-012) — the same gate the file download enforces.
    from foragerr.ddl.download import build_allowlist, build_hop_check

    hop_check = build_hop_check(build_allowlist(settings.base_url))

    try:
        for tier, query in ladder:
            tier_candidates = await _walk_tier(
                factory=factory,
                base_url=settings.base_url,
                query=query,
                tier=tier,
                max_pages=settings.max_pages,
                row=row,
                seen_urls=seen_urls,
                config_dir=cfg_dir,
                min_interval=settings.effective_min_interval(),
                sleep=sleep,
                clock=clock,
                rand=rand,
                hop_check=hop_check,
            )
            outcome.candidates.extend(tier_candidates)
            # Escalate only when a tier produced nothing (FRG-DDL-002).
            if tier_candidates:
                break
    except AdapterDrift as drift:
        logger.warning(
            "ddl: GetComics adapter drift on %s page; degrading provider",
            drift.kind,
            extra={"indexer_id": row.id, "reason": drift.reason},
        )
        outcome.candidates = []
        outcome.failure = IndexerUnavailable(str(drift))
        await backoff.record_failure(
            PROVIDER_DDL, row.id, reason=f"adapter drift: {drift.reason}"
        )
        return outcome
    except _ProviderBackoffEngaged as engaged:
        logger.info(
            "ddl: GetComics self-protection (%s); engaging back-off",
            engaged.reason,
            extra={"indexer_id": row.id},
        )
        outcome.candidates = []
        outcome.failure = IndexerUnavailable(engaged.reason)
        await backoff.record_failure(
            PROVIDER_DDL,
            row.id,
            reason=engaged.reason,
            fast_forward=engaged.fast_forward,
            retry_after=engaged.retry_after,
        )
        return outcome

    await backoff.record_success(PROVIDER_DDL, row.id)
    return outcome


__all__ = ["build_query_ladder", "search_getcomics"]
