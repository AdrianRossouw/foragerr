"""Download-client implementations + the shared contract (FRG-DL-001).

:mod:`foragerr.downloads.clients.base` holds the pinned cross-area contract
(``DownloadClient`` / ``ClientItem`` / ``ClientItemStatus`` / ``ClientTestResult``)
the tracking and ddl areas code against; :mod:`.sabnzbd` is the first baseline
implementation. The built-in DDL client is added by the ddl worktree area.
"""

from foragerr.downloads.clients.base import (
    ClientItem,
    ClientItemStatus,
    ClientTestResult,
    DownloadClient,
)
from foragerr.downloads.clients.sabnzbd import SabnzbdClient

__all__ = [
    "ClientItem",
    "ClientItemStatus",
    "ClientTestResult",
    "DownloadClient",
    "SabnzbdClient",
]
