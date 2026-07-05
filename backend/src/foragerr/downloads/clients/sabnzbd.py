"""The SABnzbd download client (FRG-DL-003/004/005).

Implements the :class:`~foragerr.downloads.clients.base.DownloadClient` protocol
over SABnzbd's HTTP API. The deliberate divergences from Mylar (design decision
2) are:

- **server-side NZB fetch** (FRG-DL-003): foragerr itself fetches the NZB bytes
  from the indexer via the ``external`` egress profile — through the indexer's
  back-off ladder — validates them (non-empty, parse under the ONE hardened
  defusedxml site, ≥1 file segment), then uploads via ``mode=addfile``. Indexer
  credentials never reach SABnzbd, and a hostile/empty NZB is a typed grab
  failure, never POSTed.
- **local-service egress** (FRG-DL-003): every SAB API call uses the
  ``local-service`` profile against the operator-configured base URL, with the
  API key as a redaction-registered ``SecretStr``.
- **typed state mapping** (FRG-DL-004): ``mode=queue`` + ``mode=history``,
  category-filtered, sizes normalized to bytes, SAB states mapped onto the
  common :class:`ClientItemStatus`; ``ENCRYPTED/``-prefixed / password items are
  reported failed with a reason.
- **remote path mapping** (FRG-DL-005): completed output paths are rewritten
  through the client's mappings; a foreign, unmapped path becomes a ``warning``
  item rather than a silent import failure.

SAB-API failures are surfaced as the typed
:class:`~foragerr.downloads.errors.DownloadClientUnreachableError` (retryable);
NZB-content failures as :class:`~foragerr.downloads.errors.GrabValidationError`.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import TYPE_CHECKING, Any, Mapping

from foragerr.downloads.clients.base import (
    ClientItem,
    ClientItemStatus,
    ClientTestResult,
)
from foragerr.downloads.errors import (
    DownloadClientUnreachableError,
    GrabValidationError,
)
from foragerr.downloads.pathmap import RemotePathMapping, apply_mappings
from foragerr.downloads.settings import SabnzbdSettings
from foragerr.http import HttpClientFactory, OutboundHttpError
from foragerr.indexers.errors import IndexerMalformedError
from foragerr.indexers.xml import parse_indexer_xml
from foragerr.security.paths import safe_path_component
from foragerr.logging import register_secret
from foragerr.providers.backoff import (
    PROVIDER_DOWNLOAD_CLIENT,
    PROVIDER_INDEXER,
    ProviderBackoff,
)
from foragerr.search_ops.grab import GrabReleaseCommand

if TYPE_CHECKING:
    from foragerr.downloads.registry import ClientBuildContext

logger = logging.getLogger("foragerr.downloads.sabnzbd")

#: NZB response byte cap for the server-side fetch (ample per NZB, under ceiling).
NZB_MAX_BYTES = 16_000_000

#: SAB queue statuses that map onto each common status (lowercased, FRG-DL-004).
_QUEUE_QUEUED = frozenset({"queued", "grabbing", "propagating", "fetching"})
_QUEUE_DOWNLOADING = frozenset(
    {"downloading", "checking", "verifying", "extracting", "repairing", "moving"}
)
#: History in-progress states (post-download processing) map to downloading.
_HISTORY_DOWNLOADING = frozenset(
    {"extracting", "verifying", "repairing", "running", "queued", "downloading"}
)
#: fail_message fragments that make a SAB failure a WARNING, not a FAILED
#: (disk-full unpack — recoverable operator condition, FRG-DL-004). Fragments are
#: specific ("no space", not a bare "space" that would also match "namespace").
_DISK_FULL_FRAGMENTS = ("no space", "disk full", "not enough space")
#: fail_message / name fragments marking an encrypted / password-protected item.
_ENCRYPTED_PREFIX = "ENCRYPTED/"
_PASSWORD_FRAGMENTS = ("encrypted", "password")


class SabnzbdClient:
    """Async SABnzbd client bound to one ``download_clients`` row.

    Construct via :meth:`from_context`; the resolver / test endpoint supply the
    build context. Statelessly reuses the shared HTTP factory per call.
    """

    def __init__(
        self,
        settings: SabnzbdSettings,
        http_factory: HttpClientFactory,
        *,
        backoff: ProviderBackoff,
        client_id: int,
        mappings: list[RemotePathMapping] | None = None,
        remove_completed_downloads: bool = True,
    ) -> None:
        base = settings.base_url.rstrip("/")
        self._api_url = base if base.endswith("/api") else f"{base}/api"
        self._base_url = base
        self._api_key = settings.api_key.get_secret_value()
        register_secret(self._api_key)  # redaction (env-credentials memory)
        self._category = settings.category
        self._priority = settings.priority
        self._factory = http_factory
        self._backoff = backoff
        self._client_id = client_id
        self._mappings = list(mappings or [])
        self._remove_completed = remove_completed_downloads

    @classmethod
    def from_context(cls, ctx: "ClientBuildContext") -> "SabnzbdClient":
        """Build a client from a :class:`ClientBuildContext` (registry factory)."""
        settings = ctx.settings
        assert isinstance(settings, SabnzbdSettings)  # registry guarantees the type
        return cls(
            settings,
            ctx.http_factory,
            backoff=ctx.backoff,
            client_id=ctx.row.id,
            mappings=ctx.mappings,
            remove_completed_downloads=ctx.row.remove_completed_downloads,
        )

    @property
    def client_id(self) -> int | None:
        """The ``download_clients`` row id this client serves (FRG-DL-006)."""
        return self._client_id

    # --- test action (FRG-DL-004 note: version + config live here) ----------

    async def test(self) -> ClientTestResult:
        """Probe SAB reachability + credentials via ``mode=version`` and sanity
        ``mode=get_config`` — the only place those checks run (FRG-DL-004)."""
        version_doc = await self._api_get({"mode": "version"})
        version = str(version_doc.get("version") or "") or None
        warnings: list[str] = []
        config = await self._api_get({"mode": "get_config"})
        categories = _config_categories(config)
        if categories and self._category.lower() not in categories:
            warnings.append(
                f"configured category {self._category!r} is not defined in "
                "SABnzbd; downloads may be filed under the default category"
            )
        return ClientTestResult(
            success=True,
            message="SABnzbd reachable; version and config retrieved",
            version=version,
            warnings=tuple(warnings),
        )

    # --- grab (FRG-DL-003) ---------------------------------------------------

    async def download(self, request: GrabReleaseCommand) -> str:
        """Fetch → validate → ``mode=addfile`` upload; return the ``nzo_id``.

        Raises :class:`DownloadClientUnreachableError` (retryable) if the indexer
        NZB fetch or the SAB API is unreachable, and :class:`GrabValidationError`
        for NZB content that fails validation or an empty ``nzo_id`` response.
        """
        nzb_bytes = await self._fetch_nzb(request)
        _validate_nzb(nzb_bytes, title=request.title)
        nzo_id = await self._add_file(nzb_bytes, request)
        if not nzo_id:
            raise GrabValidationError(
                f"SABnzbd returned no nzo_id for {request.title!r}; grab failed"
            )
        logger.info(
            "SABnzbd accepted grab",
            extra={
                "download_id": nzo_id,
                "indexer_id": request.indexer_id,
                "category": self._category,
            },
        )
        return nzo_id

    async def _fetch_nzb(self, request: GrabReleaseCommand) -> bytes:
        """Fetch NZB bytes from the indexer link, through the indexer ladder."""
        status = await self._backoff.status(PROVIDER_INDEXER, request.indexer_id)
        if status.active:
            raise DownloadClientUnreachableError(
                f"indexer {request.indexer_id} is backing off "
                f"({round(status.remaining_seconds)}s); grab retryable"
            )
        client = self._factory.external()
        try:
            result = await client.get(request.link, max_bytes=NZB_MAX_BYTES)
        except OutboundHttpError as exc:
            await self._backoff.record_failure(
                PROVIDER_INDEXER, request.indexer_id, reason=f"NZB fetch refused: {exc}"
            )
            raise DownloadClientUnreachableError(
                f"NZB fetch from indexer {request.indexer_id} failed: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 — httpx types can't be named here
            await self._backoff.record_failure(
                PROVIDER_INDEXER, request.indexer_id, reason="NZB fetch failed"
            )
            raise DownloadClientUnreachableError(
                f"NZB fetch from indexer {request.indexer_id} failed"
            ) from exc
        finally:
            await client.aclose()
        if result.status_code != 200:
            await self._backoff.record_failure(
                PROVIDER_INDEXER,
                request.indexer_id,
                reason=f"NZB fetch HTTP {result.status_code}",
            )
            raise DownloadClientUnreachableError(
                f"NZB fetch from indexer {request.indexer_id} returned HTTP "
                f"{result.status_code}"
            )
        await self._backoff.record_success(PROVIDER_INDEXER, request.indexer_id)
        return result.content

    async def _add_file(self, nzb_bytes: bytes, request: GrabReleaseCommand) -> str:
        """Upload the validated NZB via ``mode=addfile`` (multipart)."""
        boundary = "----foragerr" + secrets.token_hex(16)
        filename = _nzb_filename(request.title)
        body = _multipart_body(boundary, filename, nzb_bytes)
        headers = {"content-type": f"multipart/form-data; boundary={boundary}"}
        params: dict[str, Any] = {
            "mode": "addfile",
            "cat": self._category,
            "priority": self._priority,
            "nzbname": request.title,
        }
        doc = await self._api_request(
            "POST", params, content=body, headers=headers
        )
        nzo_ids = doc.get("nzo_ids") or []
        if not isinstance(nzo_ids, list) or not nzo_ids:
            return ""
        return str(nzo_ids[0])

    # --- polling (FRG-DL-004) ------------------------------------------------

    async def get_items(self) -> list[ClientItem]:
        """Poll ``mode=queue`` + ``mode=history``, category-filtered, typed."""
        queue = await self._api_get({"mode": "queue", "limit": 200})
        history = await self._api_get({"mode": "history", "limit": 200})
        items: list[ClientItem] = []
        for slot in _slots(queue, "queue"):
            item = self._queue_item(slot)
            if item is not None:
                items.append(item)
        for slot in _slots(history, "history"):
            item = self._history_item(slot)
            if item is not None:
                items.append(item)
        return items

    def _queue_item(self, slot: Mapping[str, Any]) -> ClientItem | None:
        category = str(slot.get("cat") or "")
        if not _category_matches(category, self._category):
            return None
        download_id = str(slot.get("nzo_id") or "")
        if not download_id:
            return None  # a slot with no id has no tracking join key — skip it
        total = _mb_to_bytes(slot.get("mb"))
        remaining = _mb_to_bytes(slot.get("mbleft"))
        return ClientItem(
            download_id=download_id,
            title=str(slot.get("filename") or slot.get("nzo_id") or ""),
            category=category,
            total_size=total,
            remaining_size=remaining,
            estimated_time=_timeleft_seconds(slot.get("timeleft")),
            output_path=None,  # no final path while still in the queue
            status=_map_queue_status(str(slot.get("status") or "")),
        )

    def _history_item(self, slot: Mapping[str, Any]) -> ClientItem | None:
        category = str(slot.get("category") or "")
        if not _category_matches(category, self._category):
            return None
        download_id = str(slot.get("nzo_id") or "")
        if not download_id:
            return None  # a slot with no id has no tracking join key — skip it
        name = str(slot.get("name") or slot.get("nzo_id") or "")
        fail_message = str(slot.get("fail_message") or "")
        total = _int_or_zero(slot.get("bytes"))
        status, encrypted, reason, remaining = _map_history_status(
            str(slot.get("status") or ""), name, fail_message, total
        )
        output_path: str | None = None
        storage = str(slot.get("storage") or "") or None
        if status is ClientItemStatus.COMPLETED and storage:
            mapped = apply_mappings(storage, self._mappings)
            output_path = mapped.path
            if mapped.warning is not None:
                # FRG-DL-005: never a silent import failure — surface a warning.
                status = ClientItemStatus.WARNING
                reason = mapped.warning
        elif storage:
            output_path = storage
        return ClientItem(
            download_id=download_id,
            title=name,
            category=category,
            total_size=total,
            remaining_size=remaining,
            estimated_time=None,
            output_path=output_path,
            status=status,
            encrypted=encrypted,
            reason=reason,
        )

    # --- removal + import cleanup (FRG-DL-001) -------------------------------

    async def remove(self, item: ClientItem, delete_data: bool) -> None:
        """Remove one item from SAB's queue or history, optionally its data."""
        del_files = "1" if delete_data else "0"
        mode = (
            "history"
            if item.status
            in (
                ClientItemStatus.COMPLETED,
                ClientItemStatus.FAILED,
                ClientItemStatus.WARNING,
            )
            else "queue"
        )
        await self._api_request(
            "GET",
            {
                "mode": mode,
                "name": "delete",
                "value": item.download_id,
                "del_files": del_files,
            },
        )

    async def mark_imported(self, item: ClientItem) -> None:
        """Signal import completion; deletes the history row when the client is
        configured to remove completed downloads, else a no-op (change 6 owns
        the full cleanup policy)."""
        if not self._remove_completed:
            return
        await self._api_request(
            "GET",
            {"mode": "history", "name": "delete", "value": item.download_id},
        )

    # --- HTTP plumbing over the local-service profile + ladder ---------------

    async def _api_get(self, params: Mapping[str, Any]) -> dict[str, Any]:
        return await self._api_request("GET", params)

    async def _api_request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """One SAB API call over the ``local-service`` profile + DL ladder.

        Raises :class:`DownloadClientUnreachableError` (retryable) on transport,
        non-200, or non-JSON responses, escalating the download-client back-off
        ladder so a downed SAB is de-prioritized (FRG-DL-002 / FRG-NFR-005).
        """
        full = {**dict(params), "apikey": self._api_key, "output": "json"}
        client = self._factory.local_service(self._base_url)
        try:
            result = await client.request(
                method, self._api_url, params=full, content=content, headers=headers
            )
        except OutboundHttpError as exc:
            await self._backoff.record_failure(
                PROVIDER_DOWNLOAD_CLIENT, self._client_id, reason=f"SAB refused: {exc}"
            )
            raise DownloadClientUnreachableError(
                f"SABnzbd request refused: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 — httpx types can't be named here
            await self._backoff.record_failure(
                PROVIDER_DOWNLOAD_CLIENT, self._client_id, reason="SAB request failed"
            )
            raise DownloadClientUnreachableError("SABnzbd request failed") from exc
        finally:
            await client.aclose()
        if result.status_code != 200:
            await self._backoff.record_failure(
                PROVIDER_DOWNLOAD_CLIENT,
                self._client_id,
                reason=f"SAB HTTP {result.status_code}",
            )
            raise DownloadClientUnreachableError(
                f"SABnzbd returned HTTP {result.status_code}"
            )
        await self._backoff.record_success(PROVIDER_DOWNLOAD_CLIENT, self._client_id)
        try:
            doc = json.loads(result.content or b"{}")
        except (json.JSONDecodeError, ValueError) as exc:
            raise DownloadClientUnreachableError(
                "SABnzbd returned a non-JSON response"
            ) from exc
        if not isinstance(doc, dict):
            raise DownloadClientUnreachableError(
                "SABnzbd returned an unexpected JSON shape"
            )
        return doc


# --- module-level pure helpers (unit-testable without a client) -------------


def _validate_nzb(nzb_bytes: bytes, *, title: str) -> None:
    """Validate fetched NZB bytes before upload (FRG-DL-003).

    Non-empty, parses under the ONE hardened defusedxml site, and contains at
    least one file segment. Any failure is a typed :class:`GrabValidationError`
    carrying a reason — the bytes are never POSTed to SABnzbd.
    """
    if not nzb_bytes.strip():
        raise GrabValidationError(f"NZB for {title!r} is empty; grab failed")
    try:
        root = parse_indexer_xml(nzb_bytes, max_bytes=NZB_MAX_BYTES)
    except IndexerMalformedError as exc:
        raise GrabValidationError(
            f"NZB for {title!r} did not parse as XML: {exc}"
        ) from exc
    has_segment = any(el.tag.split("}")[-1] == "segment" for el in root.iter())
    if not has_segment:
        raise GrabValidationError(
            f"NZB for {title!r} contains no file segments; grab failed"
        )


def _nzb_filename(title: str) -> str:
    """A safe, system-generated NZB upload filename (never remote-derived).

    Reuses the one shared :func:`safe_path_component` (as the DDL downloader does)
    rather than hand-rolling sanitization, so path-separator/traversal/reserved
    handling stays in a single audited place (FRG-NFR-012)."""
    return f"{safe_path_component(title, fallback='release')[:180]}.nzb"


def _multipart_body(boundary: str, filename: str, nzb_bytes: bytes) -> bytes:
    """Build a minimal ``multipart/form-data`` body with one ``name`` file part."""
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="name"; filename="{filename}"\r\n'
        "Content-Type: application/x-nzb\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return head + nzb_bytes + tail


def _slots(doc: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    """The ``slots`` list from a ``mode=queue``/``mode=history`` response."""
    section = doc.get(key)
    if not isinstance(section, Mapping):
        return []
    slots = section.get("slots")
    return list(slots) if isinstance(slots, list) else []


def _config_categories(doc: Mapping[str, Any]) -> set[str]:
    """Lowercased category names from a ``mode=get_config`` response."""
    config = doc.get("config")
    if not isinstance(config, Mapping):
        return set()
    categories = config.get("categories")
    if not isinstance(categories, list):
        return set()
    names: set[str] = set()
    for entry in categories:
        if isinstance(entry, Mapping) and entry.get("name"):
            names.add(str(entry["name"]).lower())
    return names


def _category_matches(item_category: str, configured: str) -> bool:
    """Category filter (FRG-DL-004): case-insensitive, ``*`` wildcard allowed.

    The wildcard is on the CONFIGURED side: ``category="*"`` claims every item.
    A SAB item whose own category is ``*`` (SAB's default/uncategorized) is NOT
    claimed unless foragerr is itself configured for ``*`` — otherwise foragerr
    would hijack uncategorized downloads other apps queued.
    """
    item = item_category.strip().lower()
    want = configured.strip().lower()
    return want == "*" or item == want


def _mb_to_bytes(value: Any) -> int:
    """SAB reports queue sizes in MB strings; normalize to bytes (FRG-DL-004)."""
    try:
        return int(round(float(value) * 1024 * 1024))
    except (TypeError, ValueError):
        return 0


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _timeleft_seconds(value: Any) -> float | None:
    """Parse SAB ``timeleft`` ``HH:MM:SS`` into seconds, or ``None``."""
    if not isinstance(value, str) or not value.strip():
        return None
    parts = value.strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    seconds = 0
    for num in nums:
        seconds = seconds * 60 + num
    return float(seconds)


def _map_queue_status(sab_status: str) -> ClientItemStatus:
    """Map a SAB queue status onto the common status (FRG-DL-004)."""
    status = sab_status.strip().lower()
    if status == "paused":
        return ClientItemStatus.PAUSED
    if status in _QUEUE_QUEUED:
        return ClientItemStatus.QUEUED
    if status in _QUEUE_DOWNLOADING:
        return ClientItemStatus.DOWNLOADING
    if status == "completed":
        return ClientItemStatus.COMPLETED
    if status == "failed":
        return ClientItemStatus.FAILED
    return ClientItemStatus.DOWNLOADING  # unknown active state → downloading


def _map_history_status(
    sab_status: str, name: str, fail_message: str, total: int
) -> tuple[ClientItemStatus, bool, str | None, int]:
    """Map a SAB history status onto (status, encrypted, reason, remaining).

    ``ENCRYPTED/``-prefixed / password items are encrypted + failed with a
    reason; a disk-full unpack failure is a warning; other failures are failed
    (FRG-DL-004).
    """
    status = sab_status.strip().lower()
    lower_fail = fail_message.lower()
    encrypted = name.startswith(_ENCRYPTED_PREFIX) or any(
        fragment in lower_fail for fragment in _PASSWORD_FRAGMENTS
    )
    if encrypted:
        reason = fail_message or "encrypted / password-protected archive"
        return ClientItemStatus.FAILED, True, reason, total
    if status == "completed":
        return ClientItemStatus.COMPLETED, False, None, 0
    if status == "failed":
        if any(fragment in lower_fail for fragment in _DISK_FULL_FRAGMENTS):
            return (
                ClientItemStatus.WARNING,
                False,
                fail_message or "disk full during unpack",
                total,
            )
        return ClientItemStatus.FAILED, False, fail_message or None, total
    if status in _HISTORY_DOWNLOADING:
        return ClientItemStatus.DOWNLOADING, False, None, total
    return ClientItemStatus.DOWNLOADING, False, None, total


__all__ = ["NZB_MAX_BYTES", "SabnzbdClient"]
