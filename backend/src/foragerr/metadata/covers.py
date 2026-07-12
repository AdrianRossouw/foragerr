"""Cover-image cache fetch (FRG-META-013).

Downloads a ComicVine cover image through the SAME process-global rate gate as
every other CV call, the SAME outbound factory (egress policy + byte cap), and
an operator-overridable host allowlist (design decision 9: the CV image host is
allowlisted via config, NOT hardcoded). The bytes are written atomically to a
caller-chosen destination; the caller (flows/api agent) owns the cache key and
directory layout (``<config>/covers/<key>.jpg``) and serves images from disk.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlsplit

from foragerr.http import HttpClientFactory, OutboundHttpError
from foragerr.metadata.comicvine import split_csv, user_agent
from foragerr.metadata.errors import (
    ComicVineError,
    ComicVineUnavailable,
    CoverHostNotAllowed,
)
from foragerr.metadata.ratelimit import effective_budget, effective_interval, gate

logger = logging.getLogger("foragerr.metadata.covers")

#: Budget bucket for cover-image fetches (FRG-META-016). Covers hit ComicVine's
#: image CDN rather than an API resource path, so they get their own named
#: bucket — but they STILL pass through the one budgeted acquire (no bypass path,
#: covers included: FRG-META-003), consuming one unit of this bucket per fetch.
COVER_BUDGET_BUCKET = "covers"


def _allowed_hosts(settings) -> frozenset[str]:
    return frozenset(h.casefold() for h in split_csv(settings.comicvine_image_hosts))


async def cache_cover(
    image_url: str,
    dest_path: Path,
    *,
    factory: HttpClientFactory,
    settings,
) -> bool:
    """Fetch ``image_url`` and write it atomically to ``dest_path``.

    Shares the process-global CV rate gate and the outbound egress/byte-cap
    policy. The image host must be on the configured
    ``comicvine_image_hosts`` allowlist. Returns ``True`` on a successful
    write. Raises:

    * :class:`CoverHostNotAllowed` — host off the allowlist;
    * :class:`ComicVineError` — malformed/forbidden-scheme URL;
    * :class:`ComicVineUnavailable` — egress refusal, non-200, transport error.

    The destination filename is caller-supplied (system-generated), never
    derived from the remote URL (FRG-NFR-012).
    """
    parsed = urlsplit(image_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ComicVineError("cover image URL is not a valid http(s) URL")
    if parsed.hostname.casefold() not in _allowed_hosts(settings):
        raise CoverHostNotAllowed(
            f"cover image host {parsed.hostname!r} is not in the configured allowlist"
        )

    await gate().acquire(
        effective_interval(settings),
        bucket=COVER_BUDGET_BUCKET,
        budget=effective_budget(settings),
    )
    async with factory.external() as client:
        try:
            result = await client.get(
                image_url, headers={"user-agent": user_agent()}
            )
        except OutboundHttpError as exc:
            raise ComicVineUnavailable(f"cover fetch refused: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — httpx types unavailable here
            raise ComicVineUnavailable("cover fetch failed") from exc

    if result.status_code != 200:
        raise ComicVineUnavailable(
            f"cover fetch returned HTTP {result.status_code}"
        )

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")
    tmp_path.write_bytes(result.content)
    tmp_path.replace(dest_path)  # atomic swap into place
    return True
