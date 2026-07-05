"""The download-client cross-area contract (FRG-DL-001).

This is the PINNED seam that makes "DDL is just another client" true instead of
Mylar's parallel DDL_QUEUE world: the SABnzbd client (this area) and the
built-in DDL client (the ddl area) both implement one :class:`DownloadClient`
protocol, and the tracking area drives both through it without ever branching on
the concrete client type. ``ClientItem`` is the uniform typed row every client's
``get_items()`` yields regardless of the client's native shape.

Nothing here does I/O — it is types only, so the tracking and ddl areas can
import the contract without pulling in httpx or SAB/GetComics specifics.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from foragerr.search_ops.grab import GrabReleaseCommand


class ClientItemStatus(StrEnum):
    """The common item status every client maps its native states onto.

    Exactly the six states FRG-DL-001 mandates; a :class:`enum.StrEnum` so a
    member equals its lowercase text (``ClientItemStatus.DOWNLOADING ==
    "downloading"``). This is the *transient* per-poll status of a client item —
    distinct from :class:`foragerr.downloads.state.TrackedDownloadState`, the
    persisted tracking-machine state the tracking area derives from it.
    """

    QUEUED = "queued"
    PAUSED = "paused"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ClientItem:
    """One download as reported by a client, normalized across clients (FRG-DL-001).

    Sizes are BYTES. ``estimated_time`` is the estimated seconds remaining
    (``float``) or ``None`` when the client cannot estimate it (e.g. a completed
    or history item). ``output_path`` is the client-reported final path, already
    remote-path-mapped by the client when applicable (FRG-DL-005), or ``None``
    while still downloading. ``encrypted`` / ``reason`` carry the encrypted /
    password-protected and failure-reason detail (FRG-DL-004).
    """

    download_id: str
    title: str
    category: str
    total_size: int
    remaining_size: int
    estimated_time: float | None
    output_path: str | None
    status: ClientItemStatus
    encrypted: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ClientTestResult:
    """The typed result of a client's ``test()`` connectivity/credentials probe.

    ``version`` is the client-reported version string when the probe read it
    (e.g. SABnzbd ``mode=version``), else ``None``. ``warnings`` carries
    non-fatal config-sanity findings (e.g. ``mode=get_config`` mismatches) that
    should surface without failing the test.
    """

    success: bool
    message: str
    version: str | None = None
    warnings: tuple[str, ...] = ()


@runtime_checkable
class DownloadClient(Protocol):
    """The one interface SABnzbd and the built-in DDL client both implement.

    The tracking loop and queue view operate through THIS surface alone — no
    client-specific method is reachable by a caller (FRG-DL-001). Every method
    is asynchronous; ``download`` consumes the frozen change-4
    :class:`~foragerr.search_ops.grab.GrabReleaseCommand` (reading its
    ``link`` / ``indexer_id`` / ``title`` / ``size_bytes``) and returns the
    client-side download id that becomes the tracking join key.
    """

    @property
    def client_id(self) -> int | None:
        """The ``download_clients`` row id this client is bound to (FRG-DL-006).

        Stamped onto every ``grab_history`` / ``tracked_downloads`` row so the
        tracking loop can attribute a download to its owning client. Part of the
        contract so a caller never reaches a private attribute; a client not
        backed by a persisted row returns ``None``.
        """
        ...

    async def test(self) -> ClientTestResult:
        """Probe connectivity + credentials without changing any state."""
        ...

    async def download(self, request: GrabReleaseCommand) -> str:
        """Grab one approved release; return the client-side download id."""
        ...

    async def get_items(self) -> list[ClientItem]:
        """List this client's downloads as uniform :class:`ClientItem`s."""
        ...

    async def remove(self, item: ClientItem, delete_data: bool) -> None:
        """Remove one item from the client, optionally deleting its data."""
        ...

    async def mark_imported(self, item: ClientItem) -> None:
        """Signal the client that ``item`` has been imported (cleanup hook)."""
        ...


__all__ = [
    "ClientItem",
    "ClientItemStatus",
    "ClientTestResult",
    "DownloadClient",
]
