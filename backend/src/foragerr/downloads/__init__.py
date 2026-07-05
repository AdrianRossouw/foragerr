"""The download-client foundation (change 5, area: downloads — FRG-DL-001..005).

The foundation the tracking + ddl areas build on:

- the pinned :class:`~foragerr.downloads.clients.base.DownloadClient` protocol +
  :class:`~foragerr.downloads.clients.base.ClientItem` (FRG-DL-001);
- the ``download_clients`` provider table + registry + schema/test endpoints,
  reusing the change-4 provider machinery generically (FRG-DL-002);
- the SABnzbd client (FRG-DL-003/004) with remote path mapping (FRG-DL-005);
- the canonical :class:`~foragerr.downloads.state.TrackedDownloadState` enum
  (FRG-DL-007) the tracking area drives;
- :func:`~foragerr.downloads.resolver.resolve_client_for` — the grab-dispatch
  client selection the tracking area's live grab handler calls (FRG-DL-002).

Importing this package pulls in the ORM models so the six change-5 tables are
mapped on ``Base.metadata``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from foragerr.downloads.clients.base import (
    ClientItem,
    ClientItemStatus,
    ClientTestResult,
    DownloadClient,
)
from foragerr.downloads.errors import (
    DownloadClientError,
    DownloadClientUnreachableError,
    GrabValidationError,
    NoDownloadClientError,
)
from foragerr.downloads.models import (
    BlocklistRow,
    DdlQueueRow,
    DownloadClientRow,
    GrabHistoryRow,
    RemotePathMappingRow,
    TrackedDownloadRow,
)
from foragerr.downloads.resolver import (
    protocol_for_grab,
    protocol_for_indexer,
    resolve_client_for,
    resolve_client_for_grab,
)
from foragerr.downloads.state import TrackedDownloadState

if TYPE_CHECKING:
    from foragerr.config import Settings
    from foragerr.http import HttpClientFactory


def make_download_factory(settings: "Settings") -> "HttpClientFactory":
    """Build the outbound HTTP factory for download-client traffic.

    The single indirection tests monkeypatch (and the schema/test endpoint
    prefers an ``app.state.http_factory`` override over) — mirrors
    ``search_ops.make_indexer_factory``. SAB API calls resolve through the
    ``local-service`` profile of this factory, NZB fetches through ``external``.
    """
    from foragerr.http import HttpClientFactory

    return HttpClientFactory(settings)


__all__ = [
    "BlocklistRow",
    "ClientItem",
    "ClientItemStatus",
    "ClientTestResult",
    "DdlQueueRow",
    "DownloadClient",
    "DownloadClientError",
    "DownloadClientRow",
    "DownloadClientUnreachableError",
    "GrabHistoryRow",
    "GrabValidationError",
    "NoDownloadClientError",
    "RemotePathMappingRow",
    "TrackedDownloadRow",
    "TrackedDownloadState",
    "make_download_factory",
    "protocol_for_grab",
    "protocol_for_indexer",
    "resolve_client_for",
    "resolve_client_for_grab",
]
