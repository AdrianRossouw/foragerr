"""The built-in DDL download client (FRG-DDL-001).

Implements the ONE :class:`~foragerr.downloads.clients.base.DownloadClient`
protocol the SABnzbd client also implements, so a DDL grab is "just another
client" (design decision 5 — no parallel Mylar DDL world): it receives a
download id, appears in the shared tracked-download queue distinguishable only
by its protocol/client fields, and flows the same completed/failed handling as
SAB. ``download`` enqueues into the ``ddl_queue`` engine and returns the id;
``get_items`` projects ``ddl_queue`` rows into uniform :class:`ClientItem`s (the
completed→import / failed→blocklist transitions are the tracking area's job,
driven off those projected items).
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from foragerr.config import Settings
from foragerr.ddl.links import parse_host_priority
from foragerr.ddl.queue import (
    STATUS_ABORTED,
    STATUS_COMPLETED,
    STATUS_DOWNLOADING,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_QUEUED,
    DdlQueueEngine,
    EnqueueRequest,
)
from foragerr.ddl.state import resolve_config_dir
from foragerr.downloads.clients.base import (
    ClientItem,
    ClientItemStatus,
    ClientTestResult,
)
from foragerr.downloads.models import DdlQueueRow
from foragerr.downloads.settings import BuiltinDdlSettings
from foragerr.http import HttpClientFactory
from foragerr.search_ops.grab import GrabReleaseCommand

if TYPE_CHECKING:
    from foragerr.downloads.registry import ClientBuildContext

logger = logging.getLogger("foragerr.ddl.client")

#: ddl_queue.status → the common ClientItem status (FRG-DDL-001).
_STATUS_MAP: dict[str, ClientItemStatus] = {
    STATUS_QUEUED: ClientItemStatus.QUEUED,
    STATUS_DOWNLOADING: ClientItemStatus.DOWNLOADING,
    STATUS_COMPLETED: ClientItemStatus.COMPLETED,
    STATUS_FAILED: ClientItemStatus.FAILED,
    STATUS_PAUSED: ClientItemStatus.PAUSED,
    STATUS_ABORTED: ClientItemStatus.FAILED,
}


def make_ddl_factory(settings: Settings) -> HttpClientFactory:
    """Build the outbound factory for DDL traffic (tests monkeypatch this to
    route at an injected transport, mirroring the indexer factory indirection)."""
    return HttpClientFactory(settings)


def staging_dir_for(config_dir: Path) -> Path:
    """The DDL staging directory: ``<config>/ddl-staging``."""
    return Path(config_dir) / "ddl-staging"


class DdlClient:
    """Async built-in DDL client bound to one ``download_clients`` row."""

    def __init__(
        self,
        settings: BuiltinDdlSettings,
        http_factory: HttpClientFactory,
        *,
        db,
        config_dir: Path,
        client_id: int | None = None,
    ) -> None:
        self._settings = settings
        self._factory = http_factory
        self._db = db
        self._staging = staging_dir_for(config_dir)
        self._client_id = client_id

    @property
    def client_id(self) -> int | None:
        """The ``download_clients`` row id this client serves (FRG-DL-006), or
        ``None`` when built without one (e.g. a bare test construction)."""
        return self._client_id

    @classmethod
    def from_context(cls, ctx: "ClientBuildContext") -> "DdlClient":
        """Build a client from a :class:`ClientBuildContext` (registry factory)."""
        settings = ctx.settings
        assert isinstance(settings, BuiltinDdlSettings)  # registry guarantees type
        config_dir = (
            Path(ctx.app_settings.config_dir)
            if ctx.app_settings is not None
            else resolve_config_dir()
        )
        return cls(
            settings,
            ctx.http_factory,
            db=ctx.db,
            config_dir=config_dir,
            client_id=ctx.row.id,
        )

    def _engine(self) -> DdlQueueEngine:
        return DdlQueueEngine(
            self._db,
            http_factory=self._factory,
            staging_dir=self._staging,
            host_priority=parse_host_priority(self._settings.host_priority),
            prefer_upscaled=self._settings.prefer_upscaled,
        )

    # -- DownloadClient protocol ---------------------------------------------

    async def test(self) -> ClientTestResult:
        """Confirm the staging directory is usable (no remote call needed)."""
        try:
            self._staging.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return ClientTestResult(
                success=False, message=f"DDL staging dir not writable: {exc}"
            )
        return ClientTestResult(
            success=True,
            message=f"DDL ready; staging at {self._staging}",
        )

    async def download(self, request: GrabReleaseCommand) -> str:
        """Enqueue one approved DDL release; return its download id (FRG-DDL-001).

        The grab's ``link`` is the GetComics *post URL* (the DDL search provider
        emits ``link == post_url``); the queue engine resolves download links
        from it. Provenance ``source=ddl`` is carried by the ``ddl`` protocol on
        the client row + provider id on the queue row."""
        download_id = f"ddl-{uuid.uuid4().hex[:16]}"
        await self._engine().enqueue(
            EnqueueRequest(
                download_id=download_id,
                post_url=request.link,
                title=request.title,
                series_id=request.series_id,
                issue_id=request.issue_id,
                provider_id=request.indexer_id,
                expected_size=request.size_bytes,
            )
        )
        logger.info(
            "ddl: grab enqueued",
            extra={"download_id": download_id, "issue_id": request.issue_id},
        )
        return download_id

    async def get_items(self) -> list[ClientItem]:
        """Project every ``ddl_queue`` row into a uniform :class:`ClientItem`."""
        async with self._db.read_session() as session:
            rows = (
                (await session.execute(select(DdlQueueRow))).scalars().all()
            )
        return [self._to_item(row) for row in rows]

    def _to_item(self, row: DdlQueueRow) -> ClientItem:
        status = _STATUS_MAP.get(row.status, ClientItemStatus.DOWNLOADING)
        total = row.expected_size or row.bytes_received or 0
        remaining = max(0, total - row.bytes_received) if total else 0
        reason: str | None = row.last_error
        if row.status == STATUS_ABORTED:
            reason = row.last_error or "aborted by user"
        return ClientItem(
            download_id=row.download_id,
            title=row.title or row.download_id,
            category="ddl",
            total_size=total,
            remaining_size=remaining if status is not ClientItemStatus.COMPLETED else 0,
            estimated_time=None,
            output_path=row.output_path
            if status is ClientItemStatus.COMPLETED
            else None,
            status=status,
            reason=reason,
        )

    async def remove(self, item: ClientItem, delete_data: bool) -> None:
        """Remove one item from the queue, optionally deleting its files."""
        await self._engine().remove(item.download_id, delete_data=delete_data)

    async def mark_imported(self, item: ClientItem) -> None:
        """Signal import completion: drop the queue row + its staged file."""
        await self._engine().remove(item.download_id, delete_data=True)


__all__ = ["DdlClient", "make_ddl_factory", "staging_dir_for"]
