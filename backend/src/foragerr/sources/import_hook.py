"""Import-completion → entitlement + edition-reconcile hook (FRG-SRC-006/007).

The completed-download drain (:mod:`foragerr.downloads.imports`) is source-
agnostic. A store grab enters that pipeline as a normal completed download whose
``download_id`` is ``humble:{entitlement_id}``. This module is the ONE small seam
that couples the import terminal state back onto the store entitlement, keyed
purely by that ``humble:`` prefix — no source-awareness is smeared through the
import pipeline.

On the import terminal transition the drain calls :func:`apply_source_import`
inside the SAME write transaction that wrote the ``issue_files`` rows, so:

* the entitlement's ``download_state`` mirrors the import verdict atomically
  (``imported`` / ``import_blocked`` / ``failed``) — so an entitlement is only
  ever ``imported`` once the file is durably in the library (FRG-SRC-006); and
* on success, every imported issue is reconciled as a possible collected edition
  (:func:`~foragerr.sources.reconcile.apply_owned_via_edition`) — a no-op for an
  ordinary single, but for a trade that declares containment it fills the covered
  singles owned-via-edition in the same commit (FRG-SRC-007). Filled singles
  therefore become owned atomically with the trade's own import.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.downloads.state import TrackedDownloadState
from foragerr.sources.models import SourceEntitlementRow
from foragerr.sources.reconcile import apply_owned_via_edition

logger = logging.getLogger("foragerr.sources.import_hook")

#: The download-id prefix marking a store-grab completed download.
HUMBLE_DOWNLOAD_PREFIX = "humble:"


def entitlement_id_from_download_id(download_id: str) -> int | None:
    """The store entitlement id encoded in a ``humble:<id>`` download id, else None."""
    if not download_id.startswith(HUMBLE_DOWNLOAD_PREFIX):
        return None
    try:
        return int(download_id[len(HUMBLE_DOWNLOAD_PREFIX) :])
    except ValueError:
        return None


async def apply_source_import(
    session: AsyncSession,
    *,
    download_id: str,
    final_state: TrackedDownloadState,
    imported_issues: list[tuple[int, str]],
    now: dt.datetime,
) -> None:
    """Mirror an import terminal state onto a store entitlement (+ reconcile).

    ``imported_issues`` is ``(issue_id, imported_path)`` for every candidate that
    imported (empty for a block/fail). No-op for a non-store ``download_id`` or a
    vanished entitlement. Runs in the caller's transaction so the entitlement
    state, the ``issue_files`` rows, and any owned-via-edition fills commit as one.
    """
    ent_id = entitlement_id_from_download_id(download_id)
    if ent_id is None:
        return
    row = await session.get(SourceEntitlementRow, ent_id)
    if row is None:
        return
    if final_state is TrackedDownloadState.IMPORTED:
        row.download_state = "imported"
        row.download_error = None
        for issue_id, path in imported_issues:
            # A no-op for an ordinary single (standalone fill-set); for a
            # collected edition it fills the covered singles owned-via-edition
            # in THIS transaction (FRG-SRC-007).
            await apply_owned_via_edition(
                session, trade_issue_id=issue_id, edition_file_path=path, now=now
            )
    elif final_state is TrackedDownloadState.IMPORT_BLOCKED:
        row.download_state = "import_blocked"
    elif final_state is TrackedDownloadState.FAILED_PENDING:
        row.download_state = "failed"
        row.download_error = (
            "import failed — the downloaded archive was rejected by the importer"
        )
    else:
        return
    row.updated_at = now


__all__ = [
    "HUMBLE_DOWNLOAD_PREFIX",
    "apply_source_import",
    "entitlement_id_from_download_id",
]
