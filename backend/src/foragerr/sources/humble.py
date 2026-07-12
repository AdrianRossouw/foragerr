"""The Humble Bundle order-API client (FRG-SRC-002/003, FRG-NFR-005/006).

A thin, hardened client over the shared outbound factory's ``external`` profile
(SSRF egress policy, TLS-verify-always, bounded timeouts, byte cap, bounded
redirect walk) — the only way Humble is reached. The store-controlled JSON is
UNTRUSTED (FRG-NFR-012): every response is byte-capped, pydantic-validated with
defensive defaults, string fields are sanitized through the shared ComicVine
sanitizer (FRG-META-014), and a single malformed subproduct is skipped-and-
logged rather than aborting the whole sync (humble-cli's own precedent — see
``docs/research/humble-api.md``).

Endpoints (``https://www.humblebundle.com``, confirmed by prior-art dissection):

* ``GET /api/v1/user/order`` → ``[{"gamekey": "..."}]`` — the owned orders.
* ``GET /api/v1/order/{gamekey}?all_tpkds=true`` → order detail with
  ``subproducts[].downloads[].download_struct[]`` (format label, md5, file_size,
  and the signed time-limited ``url.web`` we deliberately DO NOT store).

Authentication is the operator's ``_simpleauth_sess`` session cookie, sent as a
``Cookie`` header; the factory strips it on any cross-host redirect (FRG-SEC-001)
and the log filter redacts it (FRG-SRC-002). HTTP status maps to typed failures
the sync consumes: an auth failure (401/403) drives the ``expired`` state
machine (FRG-SRC-005); everything else is a transient ``HumbleUnavailable``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, ValidationError

from foragerr.db.migrations import app_version
from foragerr.http import HttpClientFactory, OutboundHttpError, parse_retry_after
from foragerr.metadata.sanitize import sanitize_cv_text
from foragerr.sources import ratelimit
from foragerr.sources.classify import DownloadOption, classify, preferred_option

logger = logging.getLogger("foragerr.sources.humble")

#: The Humble API origin — every request goes here (single-host allowlist by
#: construction; the signed download CDN host is the download worker's concern).
HUMBLE_API_BASE = "https://www.humblebundle.com"

#: Byte caps on the two untrusted responses (well under the factory ceiling).
ORDER_LIST_MAX_BYTES = 4_000_000
ORDER_DETAIL_MAX_BYTES = 8_000_000

#: Hard caps bounding a hostile payload even within the byte cap.
MAX_GAMEKEYS = 50_000
MAX_SUBPRODUCTS = 5_000
MAX_DOWNLOAD_STRUCTS = 200

#: Length cap applied to every store-supplied display string after sanitizing.
MAX_FIELD_LENGTH = 500

#: Upper bound on an accepted ``file_size`` — a hostile huge integer is dropped
#: to ``None`` rather than stored (defence for the typed column). 50 GiB is far
#: beyond any real comic archive.
_MAX_FILE_SIZE = 50 * 1024**3


@lru_cache(maxsize=1)
def user_agent() -> str:
    """The honest ``foragerr/<version>`` User-Agent (resolved once)."""
    return f"foragerr/{app_version()}"


# --- typed errors (transport-free, house convention) ------------------------


class HumbleError(Exception):
    """Base class for every Humble client failure."""


class HumbleAuthError(HumbleError):
    """The Humble session cookie was rejected (HTTP 401/403).

    Drives the ``expired`` source state (FRG-SRC-005): sync pauses with no
    automatic retry against the dead session until the operator re-pastes.
    """


class HumbleUnavailable(HumbleError):
    """A transient Humble failure — a 5xx/429, an egress refusal, an oversize
    body, or a transport/timeout error. The sync backs off; it is NOT an auth
    expiry (the cookie may still be good)."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class HumbleMalformedError(HumbleError):
    """The response body was not the expected JSON shape (whole-body malformed).

    A single malformed *subproduct* is skipped, not raised — this is only for a
    body that is not even parseable JSON of the right top-level type.
    """


# --- untrusted-JSON leaf models (FRG-NFR-012) -------------------------------


class _DownloadStruct(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = None
    md5: str | None = None
    file_size: int | None = None
    url: dict[str, Any] | None = None


class _Download(BaseModel):
    model_config = ConfigDict(extra="ignore")
    platform: str | None = None
    download_struct: list[_DownloadStruct] = []


class _Subproduct(BaseModel):
    model_config = ConfigDict(extra="ignore")
    machine_name: str
    human_name: str | None = None
    publisher: str | None = None
    downloads: list[_Download] = []


# --- parsed result shapes (the sync consumes these) -------------------------


@dataclass(frozen=True, slots=True)
class ParsedEntitlement:
    """One owned subproduct, parsed + classified — the sync's diff unit."""

    gamekey: str
    machine_name: str
    human_name: str
    publisher: str | None
    classification: str  # 'comic' | 'other'
    options: tuple[DownloadOption, ...]
    preferred: DownloadOption | None


# --- helpers ----------------------------------------------------------------


def _clean(value: Any) -> str | None:
    """Sanitize one untrusted store string to bounded, control-free plain text.

    Reuses the ComicVine ingest sanitizer (FRG-META-014): HTML/script stripped,
    ANSI/control/CR-LF and Trojan-Source bidi/zero-width characters removed,
    whitespace collapsed. Then length-capped shorter than the CV cap. ``None``
    when nothing printable remains. Never raises."""
    text = sanitize_cv_text(value if isinstance(value, str) else None)
    if text is None:
        return None
    if len(text) > MAX_FIELD_LENGTH:
        text = text[:MAX_FIELD_LENGTH].rstrip()
    return text or None


def _struct_format(struct: _DownloadStruct) -> str:
    """The uppercased format token of one ``download_struct`` entry.

    Prefers the file extension of the signed ``url.web`` (the authoritative file
    type), falling back to the ``name`` label. Returns ``""`` when neither
    yields a token."""
    web = ""
    if isinstance(struct.url, dict):
        candidate = struct.url.get("web")
        if isinstance(candidate, str):
            web = candidate
    if web:
        path = urlsplit(web).path
        _, _, ext = path.rpartition(".")
        if ext and "/" not in ext and len(ext) <= 5:
            return ext.upper()
    if struct.name:
        return struct.name.strip().upper()
    return ""


def _clean_md5(value: Any) -> str | None:
    """An md5 must be 32 lowercase hex chars; anything else is dropped to None."""
    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    if len(token) == 32 and all(c in "0123456789abcdef" for c in token):
        return token
    return None


def _clean_size(value: Any) -> int | None:
    """A file_size must be a non-negative int within a sane bound, else None."""
    if isinstance(value, bool):
        return None
    if not isinstance(value, int):
        return None
    if value < 0 or value > _MAX_FILE_SIZE:
        return None
    return value


def _parse_subproduct(gamekey: str, raw: Any) -> ParsedEntitlement | None:
    """Map one raw subproduct to a :class:`ParsedEntitlement`, or ``None`` to
    skip it (skip-and-log-never-abort, FRG-SRC-003). Never raises."""
    try:
        sub = _Subproduct.model_validate(raw)
    except ValidationError:
        return None
    machine_name = (sub.machine_name or "").strip()
    if not machine_name:
        return None  # no stable identity — cannot diff it, so skip
    options: list[DownloadOption] = []
    for download in sub.downloads:
        platform = (download.platform or "").strip().lower()
        for struct in download.download_struct[:MAX_DOWNLOAD_STRUCTS]:
            fmt = _struct_format(struct)
            options.append(
                DownloadOption(
                    format=fmt,
                    platform=platform,
                    md5=_clean_md5(struct.md5),
                    file_size=_clean_size(struct.file_size),
                    filename=_clean(struct.name),
                )
            )
    classification = classify(options)
    preferred = preferred_option(options) if classification == "comic" else None
    human_name = _clean(sub.human_name) or machine_name
    return ParsedEntitlement(
        gamekey=gamekey,
        machine_name=machine_name[:MAX_FIELD_LENGTH],
        human_name=human_name,
        publisher=_clean(sub.publisher),
        classification=classification,
        options=tuple(options),
        preferred=preferred,
    )


def parse_order(gamekey: str, content: bytes) -> list[ParsedEntitlement]:
    """Parse one (already byte-capped) untrusted order body into entitlements.

    Whole-body malformation (non-JSON, or a top level that is not an object)
    raises :class:`HumbleMalformedError`. A single malformed subproduct inside a
    valid order is skipped with a bounded log; at most :data:`MAX_SUBPRODUCTS`
    are parsed (extras dropped with one warning). Never partially aborts a sync.
    """
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise HumbleMalformedError(
            "Humble order body was not valid JSON"
        ) from exc
    if not isinstance(data, dict):
        raise HumbleMalformedError("Humble order body was not a JSON object")
    raw_subs = data.get("subproducts")
    if raw_subs is None:
        return []
    if not isinstance(raw_subs, list):
        raise HumbleMalformedError("Humble order 'subproducts' was not a list")

    entitlements: list[ParsedEntitlement] = []
    skipped = 0
    for raw in raw_subs[:MAX_SUBPRODUCTS]:
        parsed = _parse_subproduct(gamekey, raw)
        if parsed is None:
            skipped += 1
            continue
        entitlements.append(parsed)
    if len(raw_subs) > MAX_SUBPRODUCTS:
        logger.warning(
            "Humble order %s exceeded the %d-subproduct cap; extras dropped",
            gamekey,
            MAX_SUBPRODUCTS,
        )
    if skipped:
        logger.warning(
            "Humble order %s: skipped %d malformed subproduct(s)", gamekey, skipped
        )
    return entitlements


def parse_gamekeys(content: bytes) -> list[str]:
    """Parse the order-list body into gamekeys (FRG-SRC-003).

    Raises :class:`HumbleMalformedError` on a body that is not a JSON array of
    objects. A row without a string ``gamekey`` is skipped; at most
    :data:`MAX_GAMEKEYS` are returned."""
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise HumbleMalformedError(
            "Humble order-list body was not valid JSON"
        ) from exc
    if not isinstance(data, list):
        raise HumbleMalformedError("Humble order-list body was not a JSON array")
    gamekeys: list[str] = []
    for raw in data[:MAX_GAMEKEYS]:
        if not isinstance(raw, dict):
            continue
        key = raw.get("gamekey")
        if isinstance(key, str) and key.strip():
            gamekeys.append(key.strip()[:MAX_FIELD_LENGTH])
    return gamekeys


# --- the client -------------------------------------------------------------


class HumbleClient:
    """Async Humble order-API client bound to one source's cookie + factory.

    Usable as an async context manager; otherwise call :meth:`aclose`.
    """

    def __init__(
        self,
        factory: HttpClientFactory,
        session_cookie: str,
        *,
        source_id: int,
        min_interval: float = ratelimit.DEFAULT_MIN_INTERVAL,
    ) -> None:
        self._client = factory.external()
        self._cookie = session_cookie
        self._source_id = source_id
        self._min_interval = min_interval

    async def list_gamekeys(self) -> list[str]:
        """Fetch the owned-order gamekeys (``GET /api/v1/user/order``).

        This is also the connect-time validation call: an auth failure raises
        :class:`HumbleAuthError`, everything else :class:`HumbleUnavailable` /
        :class:`HumbleMalformedError`."""
        content = await self._get("/api/v1/user/order", ORDER_LIST_MAX_BYTES)
        return parse_gamekeys(content)

    async def fetch_order(self, gamekey: str) -> list[ParsedEntitlement]:
        """Fetch + parse one order's entitlements
        (``GET /api/v1/order/{gamekey}?all_tpkds=true``)."""
        content = await self._get(
            f"/api/v1/order/{gamekey}",
            ORDER_DETAIL_MAX_BYTES,
            params={"all_tpkds": "true"},
        )
        return parse_order(gamekey, content)

    async def _get(
        self, path: str, max_bytes: int, *, params: dict[str, str] | None = None
    ) -> bytes:
        # Per-source spacing gate — applied to EVERY request incl. the fan.
        await ratelimit.acquire(self._source_id, self._min_interval)
        headers = {
            "user-agent": user_agent(),
            "accept": "application/json",
            "cookie": f"_simpleauth_sess={self._cookie}",
        }
        try:
            result = await self._client.get(
                f"{HUMBLE_API_BASE}{path}",
                params=params,
                headers=headers,
                max_bytes=max_bytes,
            )
        except OutboundHttpError as exc:
            raise HumbleUnavailable(f"Humble request refused: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — httpx types can't be named here
            raise HumbleUnavailable("Humble request failed") from exc
        self._raise_for_status(result)
        return result.content

    def _raise_for_status(self, result: Any) -> None:
        code = result.status_code
        if code == 200:
            return
        if code in (401, 403):
            raise HumbleAuthError(
                f"Humble rejected the session cookie (HTTP {code})"
            )
        if code == 429:
            raise HumbleUnavailable(
                f"Humble rate-limited (HTTP {code})",
                retry_after=parse_retry_after(result.headers),
            )
        if 500 <= code < 600:
            raise HumbleUnavailable(f"Humble server error (HTTP {code})")
        raise HumbleUnavailable(f"Humble unexpected status (HTTP {code})")

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "HumbleClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


__all__ = [
    "HUMBLE_API_BASE",
    "HumbleAuthError",
    "HumbleClient",
    "HumbleError",
    "HumbleMalformedError",
    "HumbleUnavailable",
    "ORDER_DETAIL_MAX_BYTES",
    "ORDER_LIST_MAX_BYTES",
    "ParsedEntitlement",
    "parse_gamekeys",
    "parse_order",
    "user_agent",
]
