"""Same-origin proxy for metadata covers (FRG-META-021).

The v0.9.17 SPA Content-Security-Policy (`img-src 'self' data: blob:`,
FRG-SEC-006) is deliberately self-contained — so covers from the metadata
sources (ComicVine candidates in the Add-series picker and Library-import
proposals; LOCG covers on the pull/Calendar surfaces) cannot be hotlinked.
This endpoint fetches them server-side and serves them same-origin instead,
keeping the CSP untouched.

SSRF posture, layered (FRG-PROC-006 — this is a client-supplied-URL fetch,
the most abuse-prone endpoint shape there is):

1. **Perimeter**: the route lives under ``/api/v1`` — default-deny auth
   applies; anonymous callers never reach the fetch logic.
2. **Allowlist rules**: HTTPS-only, and the target must satisfy one
   :data:`COVER_HOST_RULES` entry — a host, a subdomain policy, and an
   optional required path prefix. Two sources are allowed today:

   - the ComicVine media hosts, exact or dot-boundary subdomain, no path
     constraint (``evilcomicvine.gamespot.com.evil`` shapes can't ride the
     suffix);
   - the LOCG cover store, which lives path-style under ``/comicgeeks/`` on
     the SHARED endpoint ``s3.amazonaws.com``. A host-only entry there would
     turn this endpoint into a proxy for every public S3 bucket on the
     internet, so the rule is exact-host (no subdomain form — the same
     objects also resolve virtual-hosted at ``comicgeeks.s3.amazonaws.com``,
     which would sidestep any path constraint) plus a required prefix
     matched on a directory boundary.

   One evaluator, :func:`cover_url_allowed`, is the single source of truth:
   the request-time check, the per-hop redirect check, and the pull ingest's
   fail-closed cover validation all run the same rules.
3. **Path handling**: the path is percent-decoded ONCE for the prefix test
   and refused outright if a dot-segment or backslash survives — traversal
   is never normalized away, and the URL fetched is always the caller's
   original (canonicalized) one, never a decoded rebuild.
4. **Egress validation**: the fetch uses the hardened outbound factory's
   ``external`` profile — per-hop SSRF checks (loopback/private/link-local
   refused even via DNS tricks), TLS verified, bounded redirects with the
   hop re-check.
5. **Content verification**: magic-byte sniff BEFORE any byte is served —
   JPEG/PNG/GIF/WebP only; an HTML error page or JSON body never reaches
   the browser as an "image".
6. **Bounds**: streaming size cap; bounded in-memory LRU so the cache
   itself cannot grow without limit.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, Query, Request, Response

from foragerr.api.errors import ApiError
from foragerr.http import HttpClientFactory

logger = logging.getLogger("foragerr.api.cover_proxy")

router = APIRouter(prefix="/metadata", tags=["metadata"])


@dataclass(frozen=True)
class CoverHostRule:
    """One allowlist entry: which host, whether its subdomains count, and the
    path prefix (directory-boundary) a target on that host must sit under."""

    host: str
    allow_subdomains: bool
    required_prefix: str | None = None


#: Hosts covers may be fetched from. Grows per-host by change, never by
#: config. A shared/multi-tenant endpoint MUST be exact-host with a required
#: prefix — host alone would authorize every tenant on it.
COVER_HOST_RULES: tuple[CoverHostRule, ...] = (
    CoverHostRule("comicvine.gamespot.com", allow_subdomains=True),
    CoverHostRule("comicvine.com", allow_subdomains=True),
    CoverHostRule(
        "s3.amazonaws.com", allow_subdomains=False, required_prefix="/comicgeeks/"
    ),
)

#: Encoding layers peeled when testing a segment for traversal. Peeling is
#: refusal-only — extra layers can only make the test stricter, never let
#: through a path a single decode would have rejected.
_MAX_DECODE_PEELS = 4

_DOT_SEGMENTS = (".", "..")

#: Streaming byte cap — CV covers are tens to a few hundred KiB; 2 MiB is
#: generous headroom, never a whole-archive accident.
MAX_COVER_BYTES = 2 * 1024 * 1024

#: Bounded proxy cache: picker sessions re-request the same dozen covers.
_CACHE_CAPACITY = 64

#: (magic prefix, content type) — sniffed, never trusted from the remote.
_IMAGE_MAGICS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

_cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()


def _path_is_clean(path: str) -> bool:
    """False if any segment is a dot-segment or carries a backslash, at any
    encoding depth. Such a path is refused outright rather than normalized:
    what it would have resolved to upstream never enters the decision."""
    for segment in path.split("/"):
        candidate = segment
        for _ in range(_MAX_DECODE_PEELS):
            if candidate in _DOT_SEGMENTS or "\\" in candidate:
                return False
            peeled = unquote(candidate)
            if peeled == candidate:
                break
            candidate = peeled
    return True


def _target_allowed(scheme: str, host: str, path: str) -> bool:
    """Rule evaluation over already-split parts. ``path`` is the path as sent
    (still percent-encoded); it is decoded exactly once here."""
    if scheme != "https" or not host:
        return False
    host = host.lower()
    decoded = unquote(path) or "/"
    if not decoded.startswith("/") or not _path_is_clean(decoded):
        return False
    for rule in COVER_HOST_RULES:
        if host != rule.host and not (
            rule.allow_subdomains and host.endswith("." + rule.host)
        ):
            continue
        if rule.required_prefix and not decoded.startswith(rule.required_prefix):
            continue
        return True
    return False


def cover_url_allowed(url: str) -> bool:
    """May foragerr fetch this cover URL? (FRG-META-021)

    The single source of truth for the allowlist rules, shared by the
    request-time check, the per-hop redirect check, and the pull ingest's
    fail-closed validation of source-supplied cover URLs. HTTPS-only; host
    must satisfy a :data:`COVER_HOST_RULES` entry including its subdomain
    policy and required path prefix; the query string is not consulted.
    """
    parts = urlsplit(url)
    return _target_allowed(parts.scheme, parts.hostname or "", parts.path)


def _hop_path(url) -> str:
    """The hop's path as SENT. ``httpx.URL.path`` is already decoded once, so
    reading it would decode twice and blur what the remote actually receives;
    ``raw_path`` (path + query, bytes) is the wire form."""
    raw = getattr(url, "raw_path", None)
    if raw:
        text = raw.decode("ascii", "replace") if isinstance(raw, bytes) else str(raw)
        return text.split("?", 1)[0]
    # No wire form available: "/" satisfies no prefix-constrained rule.
    return getattr(url, "path", "") or "/"


def _hop_check(url) -> None:
    """Per-hop validator handed to the factory: every hop of the redirect
    walk — not just the first URL — is re-evaluated against the same rules,
    so a hop to another host, or to a shared-host path outside the required
    prefix, is refused mid-flight."""
    scheme = getattr(url, "scheme", "")
    host = getattr(url, "host", "") or ""
    if not _target_allowed(scheme, host, _hop_path(url)):
        raise ValueError(
            f"cover hop {host!r} (scheme {scheme!r}) is outside the cover allowlist"
        )


def _sniff_image(body: bytes) -> str | None:
    for magic, content_type in _IMAGE_MAGICS:
        if body.startswith(magic):
            return content_type
    # WebP: RIFF....WEBP
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    return None


def _cache_put(url: str, body: bytes, content_type: str) -> None:
    _cache[url] = (body, content_type)
    _cache.move_to_end(url)
    while len(_cache) > _CACHE_CAPACITY:
        _cache.popitem(last=False)


def reset_cache() -> None:
    """Test hook: drop all cached covers."""
    _cache.clear()


#: Concurrent upstream fetches: the listener rate cap already bounds
#: per-client request rates, but a burst of DISTINCT cover URLs
#: from one authenticated picker session shouldn't fan out unboundedly either.
_fetch_semaphore: "asyncio.Semaphore | None" = None


def _semaphore() -> "asyncio.Semaphore":
    global _fetch_semaphore
    if _fetch_semaphore is None:
        _fetch_semaphore = asyncio.Semaphore(4)
    return _fetch_semaphore


@router.get("/cover")
async def proxy_cover(request: Request, src: str = Query(..., max_length=1024)) -> Response:
    """Fetch one allowlisted cover and serve it same-origin (FRG-META-021)."""
    parts = urlsplit(src)
    if parts.scheme != "https":
        raise ApiError(400, "cover src must be https", field="src")
    if not cover_url_allowed(src):
        raise ApiError(
            400,
            "cover src is not an allowed metadata cover target "
            "(host, subdomain, or path prefix)",
            field="src",
        )
    # Canonical cache/fetch key: case-normalized scheme+host, fragment
    # dropped, PATH LEFT AS SENT — variant spellings of one URL share one
    # cache entry and can't multiply fetches, and the fetched path is the
    # caller's, never a decoded rebuild of it.
    src = parts._replace(
        scheme="https", netloc=(parts.netloc or "").lower(), fragment=""
    ).geturl()

    cached = _cache.get(src)
    if cached is not None:
        _cache.move_to_end(src)
        body, content_type = cached
    else:
        client = HttpClientFactory(request.app.state.settings).external()
        try:
            # The factory enforces the byte cap, TLS, per-hop SSRF egress
            # checks, and the bounded redirect walk (FRG-SEC-001/NFR-006).
            # hop_check additionally re-runs the allowlist rules on EVERY hop
            # — including redirect targets: an allowlisted URL that 302s to
            # another public host, or to a shared-host path outside the
            # required prefix, is refused rather than followed (the egress
            # policy alone would allow any public host).
            async with _semaphore():
                result = await client.get(
                    src, max_bytes=MAX_COVER_BYTES, hop_check=_hop_check
                )
        except Exception as exc:  # noqa: BLE001 - upstream fetch boundary
            logger.info("cover proxy fetch failed for %s: %s", parts.hostname, exc)
            raise ApiError(502, "cover fetch failed") from exc
        finally:
            await client.aclose()
        if result.status_code != 200:
            raise ApiError(502, f"cover upstream answered {result.status_code}")
        body = result.content
        content_type = _sniff_image(body) or ""
        if not content_type:
            raise ApiError(502, "cover response is not an image")
        _cache_put(src, body, content_type)

    return Response(
        content=body,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )
