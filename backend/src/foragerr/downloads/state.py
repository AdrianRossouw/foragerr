"""The canonical tracked-download state enum (FRG-DL-007).

The single source of truth for the ``tracked_downloads.state`` text column that
the tracking area drives and the queue view (FRG-DL-008 / FRG-API-007) reads.
Defined in this foundation area so both the tracking area (which persists the
transitions) and the ddl area (which hands verified downloads to
``import_pending``) import ONE enum — the state text can never drift between
them.

Change 5 only DRIVES the download → import_pending | import_blocked | failed |
ignored subset; ``importing`` / ``imported`` are reserved for change 6's import
pipeline. All eight values are defined now so the column/enum is stable across
both changes and no migration touches the state vocabulary again.
"""

from __future__ import annotations

from enum import StrEnum


class TrackedDownloadState(StrEnum):
    """The eight tracked-download states (FRG-DL-007); values are the stored text.

    A :class:`enum.StrEnum` so a member compares/serializes as its lowercase
    text value — ``TrackedDownloadState.IMPORT_PENDING == "import_pending"`` — and
    is written to the ``tracked_downloads.state`` TEXT column verbatim.
    """

    #: The client reports the download in progress (grabbed → downloading).
    DOWNLOADING = "downloading"
    #: Completed but not yet importable — e.g. an unmapped remote path
    #: (FRG-DL-005) awaiting operator attention (change 6 surfaces it).
    IMPORT_BLOCKED = "import_blocked"
    #: Completed and awaiting the change-6 import pipeline to drain it.
    IMPORT_PENDING = "import_pending"
    #: Reserved for change 6: the import pipeline is actively importing.
    IMPORTING = "importing"
    #: Reserved for change 6: the import completed successfully.
    IMPORTED = "imported"
    #: A failure has been observed and is awaiting the failure-loop transition.
    FAILED_PENDING = "failed_pending"
    #: Terminally failed (feeds blocklist + auto re-search, FRG-DL-011/012/013).
    FAILED = "failed"
    #: Operator- or system-ignored; excluded from tracking/import handling.
    IGNORED = "ignored"


#: Tracked-download rollup status (FRG-DL-007): every state also carries an
#: ok/warning/error status independent of the state itself.
TRACKED_STATUS_OK = "ok"
TRACKED_STATUS_WARNING = "warning"
TRACKED_STATUS_ERROR = "error"

#: The subset change 5 is allowed to drive (design decision 3 note); change 6
#: owns ``importing`` / ``imported``. Exposed so the tracking area can assert it
#: never advances past ``import_pending`` in this change.
CHANGE5_DRIVEN_STATES = frozenset(
    {
        TrackedDownloadState.DOWNLOADING,
        TrackedDownloadState.IMPORT_BLOCKED,
        TrackedDownloadState.IMPORT_PENDING,
        TrackedDownloadState.FAILED_PENDING,
        TrackedDownloadState.FAILED,
        TrackedDownloadState.IGNORED,
    }
)


__all__ = [
    "CHANGE5_DRIVEN_STATES",
    "TRACKED_STATUS_ERROR",
    "TRACKED_STATUS_OK",
    "TRACKED_STATUS_WARNING",
    "TrackedDownloadState",
]
