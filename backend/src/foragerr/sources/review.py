"""Review-first entitlement workflow actions (FRG-SRC-004).

The operator's decisions between discovery and download: **match** (link a
``new`` comic entitlement to an existing library series — an operator override
that WINS over the server proposal), **add** (run the normal add-series flow —
add → refresh → scan — then link the created series), **ignore**, and
**restore** (return an ignored item to ``new`` with its proposed match
recomputed). Each has a bulk form.

Acceptance is the gate on downloading (design decision 6 / FRG-SRC-004): a
``match`` or ``add`` on a *grabbable* comic entitlement moves it to
``download_state = "queued"`` and enqueues a ``source-grab`` — so by default
nothing downloads without an explicit operator accept. The auto-sync path
(``sources.autosync``) calls these same functions for a confidently matched new
item when the per-source toggle is ON.

Every action is idempotent and preserves prior operator decisions: re-matching
is a no-op-with-update, and A1's sync diff already carries ``review_status`` /
``matched_series_id`` across re-syncs untouched.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from foragerr.db.base import utcnow
from foragerr.sources.matching import LibrarySeriesLite, compute_proposed_match
from foragerr.sources.models import SourceEntitlementRow

logger = logging.getLogger("foragerr.sources.review")


class EntitlementActionError(Exception):
    """A review action could not be applied (bad state / missing data)."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class BulkResult:
    """The outcome of a bulk review action over several entitlements."""

    applied: int
    skipped: int
    errors: dict[int, str]


def _is_grabbable(row: SourceEntitlementRow) -> bool:
    """Whether the item has a preferred copy to download (a comic with md5)."""
    return row.classification == "comic" and bool(row.md5) and bool(row.filename)


#: Download-axis states from which a (re-)accept may (re-)queue a grab. Any other
#: value (queued / fetching / verifying / import_pending / imported) means a grab
#: is already in flight or done, so re-accepting is an idempotent no-op — never a
#: second grab (FRG-SRC-004).
_QUEUEABLE_STATES = (None, "failed")


async def _queue_grab(db, entitlement_id: int, commands) -> None:
    """Mark an accepted entitlement queued and enqueue its grab (FRG-SRC-006).

    Idempotent: a grab is queued ONLY on a durable transition out of an unstarted
    (``None``) or ``failed`` download state, and the enqueue happens only when
    that transition actually occurred — so a double-accept (or a re-accept while a
    grab is in flight) never spawns a duplicate grab or tracked-download row.

    Kept import-local to avoid a module import cycle with the grab command."""
    from foragerr.sources.grab import SOURCE_GRAB_TASK

    queued = False
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        if row is None or not _is_grabbable(row):
            return
        if row.download_state not in _QUEUEABLE_STATES:
            return  # already queued / in flight / imported — no duplicate grab
        row.download_state = "queued"
        row.download_error = None  # clear a prior failure on retry
        row.updated_at = utcnow()
        queued = True
    if queued and commands is not None:
        await commands.enqueue(
            SOURCE_GRAB_TASK,
            {"entitlement_id": entitlement_id},
            triggered_by="accept",
        )


async def match_entitlement(
    db, entitlement_id: int, *, series_id: int, commands=None
) -> SourceEntitlementRow:
    """Link an entitlement to an existing library series and accept it.

    The operator's chosen ``series_id`` overrides any server proposal
    (FRG-SRC-004). Sets ``matched_series_id`` + ``review_status = "matched"`` and,
    for a grabbable comic, queues the download. Idempotent.

    The target ``series_id`` must name a real library series (a stale/garbage id
    is a 404), so a match never links an entitlement to a phantom series. When
    the entitlement was already imported against a DIFFERENT series, that prior
    series' owned-via-edition fills are reverted so the re-match does not strand
    ownership pointing at the old collected edition (FRG-SRC-007).
    """
    from foragerr.library.models import SeriesRow
    from foragerr.sources.reconcile import revert_owned_via_edition_for_series

    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        if row is None:
            raise EntitlementActionError(
                f"entitlement {entitlement_id} not found", status=404
            )
        if await session.get(SeriesRow, series_id) is None:
            raise EntitlementActionError(
                f"series {series_id} does not exist", status=404
            )
        prior_series_id = row.matched_series_id
        if (
            prior_series_id is not None
            and prior_series_id != series_id
            and row.download_state == "imported"
        ):
            await revert_owned_via_edition_for_series(
                session, series_id=prior_series_id
            )
        row.matched_series_id = series_id
        row.review_status = "matched"
        row.updated_at = utcnow()
    await _queue_grab(db, entitlement_id, commands)
    return await _reload(db, entitlement_id)


async def add_entitlement(
    db,
    settings,
    entitlement_id: int,
    *,
    commands=None,
    factory=None,
    root_folder_id: int | None = None,
    cv_volume_id: int | None = None,
) -> SourceEntitlementRow:
    """Add a brand-new series for an entitlement via the normal add flow.

    Sources the ComicVine volume id from the argument or the stored proposal
    (``proposed_match_json``), runs :func:`foragerr.library.flows.add.add_series`
    (which chains add → refresh → scan), links the created series onto the row,
    and queues the download (FRG-SRC-004/006). Raises when no CV id is available
    or no root folder is configured.
    """
    from foragerr.library import repo as library_repo
    from foragerr.library.flows.add import add_series

    row = await _reload(db, entitlement_id)
    if row is None:
        raise EntitlementActionError(
            f"entitlement {entitlement_id} not found", status=404
        )
    cvid = cv_volume_id if cv_volume_id is not None else _proposed_cv_id(row)
    if cvid is None:
        raise EntitlementActionError(
            "no ComicVine volume to add — supply cv_volume_id or match to an "
            "existing series instead",
            status=422,
        )
    root_id = root_folder_id
    if root_id is None:
        async with db.read_session() as session:
            roots = await library_repo.list_root_folders(session)
        if not roots:
            raise EntitlementActionError(
                "no root folder configured — add one before adding series",
                status=409,
            )
        root_id = roots[0].id

    try:
        result = await add_series(
            db,
            settings,
            cv_volume_id=cvid,
            root_folder_id=root_id,
            commands=commands,
            factory=factory,
        )
    except Exception as exc:  # noqa: BLE001 — surface the add failure to the API
        raise EntitlementActionError(
            f"add-series failed for volume {cvid}: {exc}", status=400
        ) from exc

    return await match_entitlement(
        db, entitlement_id, series_id=result.series.id, commands=commands
    )


async def ignore_entitlement(db, entitlement_id: int) -> SourceEntitlementRow:
    """Exclude an entitlement from pending-review counts/default views.

    It remains listed under its ``ignored`` filter; no download occurs. Idempotent.

    Ignoring also RESETS the download axis (FRG-SRC-004/006): a queued/in-flight
    grab is cancelled by clearing ``download_state`` — the in-flight ``run_grab``
    re-reads the entitlement before the irreversible import and aborts once it is
    no longer ``matched``. A grab already handed off to the import pipeline has
    its ``humble:{id}`` tracked row deleted (any state except the drain-claimed
    ``importing``) so the drain never imports the ignored item and a later
    restore + re-accept can hand off afresh; a claimed row is instead withdrawn
    by the drain's own in-transaction ``source_import_withdrawn`` re-check. An
    already-imported collected edition has its owned-via-edition fills reverted
    so the singles it provided return to wanted (real single files are never
    touched).
    """
    from sqlalchemy import delete

    from foragerr.downloads.models import TrackedDownloadRow
    from foragerr.downloads.state import TrackedDownloadState
    from foragerr.sources.import_hook import HUMBLE_DOWNLOAD_PREFIX
    from foragerr.sources.reconcile import revert_owned_via_edition_for_series

    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        if row is None:
            raise EntitlementActionError(
                f"entitlement {entitlement_id} not found", status=404
            )
        if row.download_state == "imported" and row.matched_series_id is not None:
            await revert_owned_via_edition_for_series(
                session, series_id=row.matched_series_id
            )
        # Cancel this entitlement's completed-download row (FRG-SRC-004/006).
        # DELETED (not re-stated) because the handoff dedups on download_id
        # regardless of state — any surviving row (import_pending, blocked,
        # failed_pending, imported) would silently strand a later restore +
        # re-accept with no claimable row. Only the drain-claimed ``importing``
        # row is left alone: deleting it would strand the in-flight move, and
        # the drain's in-transaction withdrawal re-check discards it instead.
        await session.execute(
            delete(TrackedDownloadRow).where(
                TrackedDownloadRow.download_id
                == f"{HUMBLE_DOWNLOAD_PREFIX}{entitlement_id}",
                TrackedDownloadRow.state
                != TrackedDownloadState.IMPORTING.value,
            )
        )
        row.review_status = "ignored"
        # Cancel any queued / in-flight / completed grab on the download axis so
        # the item is fully excluded; an in-flight grab aborts at its re-read guard.
        row.download_state = None
        row.download_error = None
        row.updated_at = utcnow()
    return await _reload(db, entitlement_id)


async def restore_entitlement(
    db, entitlement_id: int, *, cv_client=None
) -> SourceEntitlementRow:
    """Return an ignored item to ``new`` with its proposed match recomputed.

    Recomputation is library-first (and CV-backed only when a ``cv_client`` is
    supplied); a matched item that is restored drops its match target
    (FRG-SRC-004 "restore returns the item to new with its proposed match
    recomputed"). Idempotent.
    """
    from foragerr.library import repo as library_repo

    row = await _reload(db, entitlement_id)
    if row is None:
        raise EntitlementActionError(
            f"entitlement {entitlement_id} not found", status=404
        )
    async with db.read_session() as session:
        series = await library_repo.list_series(session)
    library = [
        LibrarySeriesLite(id=s.id, title=s.title, start_year=s.start_year)
        for s in series
    ]
    proposal = await compute_proposed_match(
        human_name=row.human_name, library=library, cv_client=cv_client
    )
    async with db.write_session() as session:
        fresh = await session.get(SourceEntitlementRow, entitlement_id)
        if fresh is None:
            raise EntitlementActionError(
                f"entitlement {entitlement_id} not found", status=404
            )
        fresh.review_status = "new"
        fresh.matched_series_id = None
        fresh.proposed_series_id = (
            proposal.proposed_series_id if proposal is not None else None
        )
        fresh.proposed_match_json = (
            proposal.to_json() if proposal is not None else None
        )
        fresh.updated_at = utcnow()
    return await _reload(db, entitlement_id)


# --- bulk -------------------------------------------------------------------


async def bulk_ignore(db, entitlement_ids: list[int]) -> BulkResult:
    return await _bulk(db, entitlement_ids, lambda eid: ignore_entitlement(db, eid))


async def bulk_restore(
    db, entitlement_ids: list[int], *, cv_client=None
) -> BulkResult:
    return await _bulk(
        db,
        entitlement_ids,
        lambda eid: restore_entitlement(db, eid, cv_client=cv_client),
    )


async def bulk_match(
    db, entitlement_ids: list[int], *, series_id: int, commands=None
) -> BulkResult:
    return await _bulk(
        db,
        entitlement_ids,
        lambda eid: match_entitlement(
            db, eid, series_id=series_id, commands=commands
        ),
    )


async def _bulk(db, entitlement_ids: list[int], action) -> BulkResult:
    applied = 0
    errors: dict[int, str] = {}
    for eid in entitlement_ids:
        try:
            await action(eid)
            applied += 1
        except EntitlementActionError as exc:
            errors[eid] = str(exc)
    return BulkResult(
        applied=applied, skipped=len(errors), errors=errors
    )


# --- helpers ----------------------------------------------------------------


def _proposed_cv_id(row: SourceEntitlementRow) -> int | None:
    """The ComicVine volume id from a stored proposal, if it is a CV proposal."""
    import json

    if not row.proposed_match_json:
        return None
    try:
        data = json.loads(row.proposed_match_json)
    except ValueError:
        return None
    cvid = data.get("cv_volume_id")
    return cvid if isinstance(cvid, int) else None


async def _reload(db, entitlement_id: int) -> SourceEntitlementRow | None:
    from foragerr.sources.repo import get_entitlement

    return await get_entitlement(db, entitlement_id)


__all__ = [
    "BulkResult",
    "EntitlementActionError",
    "add_entitlement",
    "bulk_ignore",
    "bulk_match",
    "bulk_restore",
    "ignore_entitlement",
    "match_entitlement",
    "restore_entitlement",
]
