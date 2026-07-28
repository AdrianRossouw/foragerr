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

**Match provenance is fail-closed (design D7).** ``matched_via`` is a REQUIRED
keyword on every function here that establishes a match. It used to default to
:data:`MATCHED_VIA_OPERATOR`, which meant a new caller that simply forgot the
argument would silently mint operator provenance — and operator provenance is
what unlocks the import pipeline's ordinal fallback (FRG-PP-022 guard 3). With
no default, the omission is a ``TypeError`` at call time instead. Nothing about
the recorded values changed: every API endpoint passes
:data:`MATCHED_VIA_OPERATOR` explicitly and ``enrich._auto_accept`` remains the
only writer of :data:`MATCHED_VIA_AUTO`.
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

    **Acceptance is re-read here, in the write transaction** (FRG-SRC-004): every
    caller validated the row in an EARLIER session, so an ``ignore`` can commit in
    between — and ignore resets ``download_state`` to ``None``, which is itself a
    queueable value, so the download-axis guard alone would happily queue an
    ignored row. That leaves a stale ``queued`` axis on an ``ignored`` item which
    ``run_grab`` then skips at its own re-read guard but never clears. Requiring
    ``review_status == "matched"`` under the writer lock closes it: the retry /
    match / add / auto-accept callers all commit ``matched`` before reaching this
    session, so a non-matched read here is always a real withdrawal.

    Kept import-local to avoid a module import cycle with the grab command."""
    from foragerr.sources.grab import SOURCE_GRAB_TASK

    queued = False
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        if row is None or not _is_grabbable(row):
            return
        if row.review_status != "matched":
            return  # ignored / restored since the caller read it — never grab
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


#: Review states an ACCEPT may act on. Accept applies a row's own *proposal*,
#: and a proposal only governs a row still in the automatic matcher's hands — a
#: matched row is already resolved and an ignored row is a withdrawal. Neither
#: may be silently re-decided by a bulk selection (FRG-SRC-011).
_ACCEPTABLE_REVIEW_STATES = ("new",)


def _accept_precondition_error(
    entitlement_id: int, review_status: str
) -> EntitlementActionError | None:
    """The per-row error for accepting a row that is no longer in review.

    ``None`` when the row is acceptable. The messages are the operator-facing
    text of the two refusals, and they are per-ROW (a bulk accept reports them
    against the id and keeps going) — never a failure of the whole request.
    """
    if review_status in _ACCEPTABLE_REVIEW_STATES:
        return None
    if review_status == "ignored":
        return EntitlementActionError(
            f"entitlement {entitlement_id} is ignored — restore it first",
            status=409,
        )
    return EntitlementActionError(
        f"entitlement {entitlement_id} is already matched — accept applies "
        "only to items still in review",
        status=409,
    )


async def match_entitlement(
    db,
    entitlement_id: int,
    *,
    series_id: int,
    commands=None,
    matched_via: str,
    require_new: bool = False,
) -> SourceEntitlementRow:
    """Link an entitlement to an existing library series and accept it.

    The operator's chosen ``series_id`` overrides any server proposal
    (FRG-SRC-004). Sets ``matched_series_id`` + ``review_status = "matched"`` and,
    for a grabbable comic, queues the download. Idempotent.

    ``matched_via`` records WHO chose the series (FRG-PP-022 guard 3) and is
    REQUIRED (design D7): a human review action passes
    :data:`MATCHED_VIA_OPERATOR`, auto-sync's ``_auto_accept`` passes
    :data:`MATCHED_VIA_AUTO`, and a caller that passes neither is a
    ``TypeError`` rather than a silent operator stamp. The import pipeline's
    ordinal fallback ("Vol. N" → issue N) fires only for an operator match.

    The target ``series_id`` must name a real library series (a stale/garbage id
    is a 404), so a match never links an entitlement to a phantom series. When
    the entitlement was already imported against a DIFFERENT series, that prior
    series' owned-via-edition fills are reverted so the re-match does not strand
    ownership pointing at the old collected edition (FRG-SRC-007).

    ``require_new`` is the ACCEPT path's precondition (FRG-SRC-011), and it is
    checked HERE — inside the write transaction that stamps ``matched`` —
    because that is the only place it closes. The accept path validated the row
    in an earlier session, so an ``ignore`` can commit in between; without an
    in-transaction re-read that ignore is silently reversed (the row flips
    ignored → matched) and :func:`_queue_grab`, seeing a legitimately
    ``matched`` row, enqueues the source-grab the operator just withdrew. The
    OPERATOR's explicit match action leaves it ``False``: choosing a series for
    an already-decided row is a legitimate re-decision, and that is the action
    the operator took.
    """
    from foragerr.library.models import SeriesRow
    from foragerr.sources.reconcile import revert_owned_via_edition_for_series

    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        if row is None:
            raise EntitlementActionError(
                f"entitlement {entitlement_id} not found", status=404
            )
        if require_new:
            refusal = _accept_precondition_error(entitlement_id, row.review_status)
            if refusal is not None:
                raise refusal
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
        row.matched_via = matched_via
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
    matched_via: str,
    require_new: bool = False,
    lane: str = "interactive",
) -> SourceEntitlementRow:
    """Add a brand-new series for an entitlement via the normal add flow.

    Sources the ComicVine volume id from the argument or the stored proposal
    (``proposed_match_json``), runs :func:`foragerr.library.flows.add.add_series`
    (which chains add → refresh → scan), links the created series onto the row,
    and queues the download (FRG-SRC-004/006). Raises when no CV id is available
    or no root folder is configured.

    **Freshness (FRG-SRC-008).** The library moves underneath a review list: a
    proposal computed at sync time may name a volume that is now present (an
    earlier add on a sibling entitlement, or a manual add). Adding it again is
    not an error the operator can act on, so the add DEGRADES to a match against
    the existing series — the identical outcome to the match action, grab
    queueing included, sibling sweep included. Only a genuine ``add_series``
    failure still surfaces as a 400. Whether the add succeeded or degraded, the
    sibling entitlements whose proposals named the same volume are re-resolved
    (:func:`_reresolve_sibling_proposals`) so their next single action succeeds on
    the first click.

    ``matched_via`` is REQUIRED (design D7) and carried onto every terminal link
    this function performs (add-then-match, degrade-to-match, and the TOCTOU
    repair) so an auto-sync add is never recorded as an operator match
    (FRG-PP-022 guard 3).

    The presence pre-check runs in its own read session, so two near-simultaneous
    adds of the same volume can both pass it; the loser's ``add_series`` rejects
    with "already in the library". That rejection is re-checked rather than
    surfaced (see the except clause) — the race lands on the same degrade path,
    never on the 400 FRG-SRC-008 exists to remove.

    ``lane`` (FRG-META-022) is passed straight to ``add_series`` for its
    ComicVine existence check. It defaults to ``interactive`` — this is the
    review screen's Add button — but auto-sync accepts through this same
    function from the nightly batch, with nobody waiting, and passes ``batch``
    so a bulk auto-accept cannot drain the operator's interactive reserve.
    """
    from foragerr.library import repo as library_repo
    from foragerr.library.flows.add import add_series

    row = await _reload(db, entitlement_id)
    if row is None:
        raise EntitlementActionError(
            f"entitlement {entitlement_id} not found", status=404
        )
    if require_new:
        # Cheap pre-check so an accept of a withdrawn row never pays for an
        # ``add_series`` (refresh + scan) it will then refuse to link. The
        # AUTHORITATIVE check is the in-transaction one in ``match_entitlement``.
        refusal = _accept_precondition_error(entitlement_id, row.review_status)
        if refusal is not None:
            raise refusal
    cvid = cv_volume_id if cv_volume_id is not None else _proposed_cv_id(row)
    if cvid is None:
        raise EntitlementActionError(
            "no ComicVine volume to add — supply cv_volume_id or match to an "
            "existing series instead",
            status=422,
        )
    # Already in the library → this is a match, not an add (FRG-SRC-008). Checked
    # BEFORE the root-folder requirement: matching needs no root folder, and a
    # rootless install would otherwise 409 on what is really a match.
    existing_series_id = await _series_id_for_volume(db, cvid)
    if existing_series_id is not None:
        return await _degrade_to_match(
            db,
            entitlement_id,
            cv_volume_id=cvid,
            series_id=existing_series_id,
            commands=commands,
            matched_via=matched_via,
            require_new=require_new,
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
            lane=lane,
        )
    except Exception as exc:  # noqa: BLE001 — surface the add failure to the API
        # TOCTOU repair (FRG-SRC-008): the pre-check and the add are separate
        # transactions, so a concurrent add of the SAME volume (a second operator,
        # or a sibling accepted at the same moment) can land in between and make
        # ``add_series`` reject with "already in the library" — the very error the
        # degrade exists to remove. Re-read: if the volume is present now, this is
        # a match, not a failure. A volume still absent means a genuine failure,
        # which still surfaces as a 400.
        raced_series_id = await _series_id_for_volume(db, cvid)
        if raced_series_id is not None:
            logger.info(
                "sources.review: add of cv volume %d raced a concurrent add; "
                "degrading to a match on series %d",
                cvid,
                raced_series_id,
            )
            return await _degrade_to_match(
                db,
                entitlement_id,
                cv_volume_id=cvid,
                series_id=raced_series_id,
                commands=commands,
                matched_via=matched_via,
                require_new=require_new,
            )
        raise EntitlementActionError(
            f"add-series failed for volume {cvid}: {exc}", status=400
        ) from exc

    # The series now exists: re-resolve every OTHER still-in-review proposal that
    # named this volume before linking the acting row (FRG-SRC-008).
    return await _resolve_as_match(
        db,
        entitlement_id,
        cv_volume_id=cvid,
        series_id=result.series.id,
        series_title=result.series.title,
        commands=commands,
        matched_via=matched_via,
        require_new=require_new,
    )


async def _resolve_as_match(
    db,
    entitlement_id: int,
    *,
    cv_volume_id: int,
    series_id: int,
    series_title: str | None,
    commands=None,
    matched_via: str,
    require_new: bool = False,
) -> SourceEntitlementRow:
    """Sweep sibling proposals for ``cv_volume_id`` then match the acting row.

    Shared tail of the add-series success path and the FRG-SRC-008 degrade: the
    other still-in-review entitlements proposing this volume are rewritten into
    library-kind match proposals before the acting row is linked, so their next
    single action succeeds on the first click too. (Without the sweep they would
    each degrade individually — correct, but only after another click apiece.)

    Sweep and match are separate transactions; the sweep only rewrites
    proposals, so a crash between the two leaves resolved proposals and an
    unlinked acting row — the same benign shape a crash mid-add already
    produces.
    """
    await _reresolve_sibling_proposals(
        db,
        cv_volume_id=cv_volume_id,
        series_id=series_id,
        series_title=series_title,
        exclude_entitlement_id=entitlement_id,
    )
    return await match_entitlement(
        db,
        entitlement_id,
        series_id=series_id,
        commands=commands,
        matched_via=matched_via,
        require_new=require_new,
    )


async def _degrade_to_match(
    db,
    entitlement_id: int,
    *,
    cv_volume_id: int,
    series_id: int,
    commands=None,
    matched_via: str,
    require_new: bool = False,
) -> SourceEntitlementRow:
    """Resolve an add whose volume is already in the library as a match.

    The FRG-SRC-008 degrade: reads the series title, then delegates to
    :func:`_resolve_as_match` for the shared sibling sweep + match tail.
    """
    from foragerr.library.models import SeriesRow

    async with db.read_session() as session:
        series = await session.get(SeriesRow, series_id)
        series_title = series.title if series is not None else None
    return await _resolve_as_match(
        db,
        entitlement_id,
        cv_volume_id=cv_volume_id,
        series_id=series_id,
        series_title=series_title,
        commands=commands,
        matched_via=matched_via,
        require_new=require_new,
    )


async def retry_download(
    db, entitlement_id: int, *, commands=None
) -> SourceEntitlementRow:
    """Re-queue a FAILED entitlement download (FRG-SRC-009).

    The explicit operator retry for the per-entitlement failed-download surface:
    valid only from ``download_state = "failed"`` (any other state is a 409 —
    there is nothing to retry, and re-queueing an in-flight or imported grab
    would duplicate work), clears the recorded ``download_error``, and re-queues
    through the standard :func:`_queue_grab` seam so the grab path, its
    idempotency, and its tracked-download handoff are unchanged.

    A stale ``humble:{id}`` tracked row is dropped first
    (:func:`_drop_stale_tracked_row`) — without that, a retry after an
    IMPORT-level failure would re-download into a no-op handoff and wedge.

    The ``failed`` validation above runs in a READ session, so an ``ignore`` can
    still commit before the grab is queued; :func:`_queue_grab` re-reads the
    acceptance inside its own write transaction, so such a retry queues nothing
    and leaves the ignored row clean.
    """
    async with db.read_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        if row is None:
            raise EntitlementActionError(
                f"entitlement {entitlement_id} not found", status=404
            )
        if row.download_state != "failed":
            state = row.download_state or "not started"
            raise EntitlementActionError(
                f"entitlement {entitlement_id} is {state}, not failed — "
                "retry applies only to a failed download",
                status=409,
            )
        if not _is_grabbable(row):
            raise EntitlementActionError(
                f"entitlement {entitlement_id} has no downloadable copy to retry",
                status=409,
            )
    await _drop_stale_tracked_row(db, entitlement_id)
    await _queue_grab(db, entitlement_id, commands)
    return await _reload(db, entitlement_id)


async def _drop_stale_tracked_row(db, entitlement_id: int) -> None:
    """Clear a retry's leftover ``humble:{id}`` tracked row (FRG-SRC-009).

    ``download_state = "failed"`` covers TWO failures: the grab failed (no tracked
    row was ever written), or the IMPORT failed — ``apply_source_import`` mirrors
    ``failed_pending`` onto the entitlement while the tracked row survives. In the
    second case a retry would re-download successfully and then hit the handoff's
    dedup (which keys on ``download_id`` regardless of state), so nothing new
    would be claimable: the entitlement would sit at ``import_pending`` forever,
    the file orphaned in staging, and a further retry would 409. So the surviving
    row is DELETED, exactly as :func:`ignore_entitlement` deletes it — and with
    the same drain-claimed carve-out, inverted: an ``importing`` row is mid-move,
    so the retry is refused rather than the row yanked out from under it.
    """
    from sqlalchemy import delete, select

    from foragerr.downloads.models import TrackedDownloadRow
    from foragerr.downloads.state import TrackedDownloadState
    from foragerr.sources.import_hook import HUMBLE_DOWNLOAD_PREFIX

    download_id = f"{HUMBLE_DOWNLOAD_PREFIX}{entitlement_id}"
    async with db.write_session() as session:
        state = await session.scalar(
            select(TrackedDownloadRow.state).where(
                TrackedDownloadRow.download_id == download_id
            )
        )
        if state is None:
            return
        if state == TrackedDownloadState.IMPORTING.value:
            raise EntitlementActionError(
                f"entitlement {entitlement_id} is being imported right now — "
                "retry once that import has finished",
                status=409,
            )
        await session.execute(
            delete(TrackedDownloadRow).where(
                TrackedDownloadRow.download_id == download_id
            )
        )
    logger.info(
        "sources.review: dropped stale tracked download %s before retry",
        download_id,
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
    db, entitlement_id: int, *, cv_client=None, cv_configured: bool = False
) -> SourceEntitlementRow:
    """Return an IGNORED item to ``new`` with its proposed match recomputed.

    **Ignored-only** (FRG-SRC-004). Restore is the inverse of ignore, and it is
    destructive to everything else: it clears ``matched_series_id`` and
    ``matched_via`` and overwrites the proposal. Applied to a ``matched`` row it
    silently unmakes the operator's match (and, in a mixed bulk restore over a
    selection that spans buckets, unmakes several at once); applied to a ``new``
    row it throws away a proposal for no gain. So both are per-row errors and
    nothing is written.

    **ComicVine is consulted when it is available** (FRG-SRC-010). Restore is an
    operator-initiated, one-row action, so the single CV call it costs is
    affordable and correct — recomputing library-only would stamp a
    ``library-fallback`` proposal on a CV-configured deployment, which the UI
    then renders as a catalog verdict and which freezes the row out of the next
    enrichment pass. Two shapes therefore leave the proposal NULL (un-proposed,
    retryable — exactly the deferral semantics of FRG-META-016) instead:

    * :class:`ComicVineBudgetExhausted` — the budget wall, caught here rather
      than surfaced, because a restore is not a failure the operator can act on;
    * a ``library-fallback`` proposal computed while ``cv_configured`` — the
      belt to the brace above: on such a deployment a fallback can only mean a
      CV call that should have happened did not.

    ``cv_configured=False`` with ``cv_client=None`` is the genuinely
    unconfigured deployment, where the library-only fallback IS the honest
    answer and is persisted as such.
    """
    from foragerr.library import repo as library_repo
    from foragerr.metadata.errors import ComicVineBudgetExhausted
    from foragerr.sources.matching import UNIVERSE_COMICVINE

    row = await _reload(db, entitlement_id)
    if row is None:
        raise EntitlementActionError(
            f"entitlement {entitlement_id} not found", status=404
        )
    if row.review_status != "ignored":
        raise EntitlementActionError(
            f"entitlement {entitlement_id} is {row.review_status}, not ignored — "
            "restore applies only to an ignored item",
            status=409,
        )
    async with db.read_session() as session:
        series = await library_repo.list_series(session)
    library = [
        LibrarySeriesLite(
            id=s.id,
            title=s.title,
            start_year=s.start_year,
            cv_volume_id=s.cv_volume_id,
        )
        for s in series
    ]
    try:
        proposal = await compute_proposed_match(
            human_name=row.human_name, library=library, cv_client=cv_client
        )
    except ComicVineBudgetExhausted as exc:
        logger.info(
            "sources.review: ComicVine budget exhausted restoring entitlement "
            "%s (%s); leaving it un-proposed and retryable",
            entitlement_id,
            exc,
        )
        proposal = None
    if (
        proposal is not None
        and cv_configured
        and proposal.universe != UNIVERSE_COMICVINE
    ):
        logger.warning(
            "sources.review: refusing to persist a %s proposal for entitlement "
            "%s on a ComicVine-configured deployment; leaving it retryable",
            proposal.universe,
            entitlement_id,
        )
        proposal = None
    async with db.write_session() as session:
        fresh = await session.get(SourceEntitlementRow, entitlement_id)
        if fresh is None:
            raise EntitlementActionError(
                f"entitlement {entitlement_id} not found", status=404
            )
        if fresh.review_status != "ignored":
            raise EntitlementActionError(
                f"entitlement {entitlement_id} is {fresh.review_status}, not "
                "ignored — restore applies only to an ignored item",
                status=409,
            )
        fresh.review_status = "new"
        fresh.matched_series_id = None
        # The match target is dropped, so its provenance goes with it — a later
        # re-match stamps its own ``matched_via`` (FRG-PP-022 guard 3).
        fresh.matched_via = None
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
    db, entitlement_ids: list[int], *, cv_client=None, cv_configured: bool = False
) -> BulkResult:
    """Restore each ignored row in the selection (per-row errors, FRG-SRC-011).

    A selection that spans review buckets — the natural result of "select all"
    over a filtered list — reports the non-ignored rows as per-row errors and
    leaves their state untouched, rather than stripping matched rows of their
    match on the way past."""
    return await _bulk(
        db,
        entitlement_ids,
        lambda eid: restore_entitlement(
            db, eid, cv_client=cv_client, cv_configured=cv_configured
        ),
    )


async def bulk_match(
    db,
    entitlement_ids: list[int],
    *,
    series_id: int,
    commands=None,
    matched_via: str,
) -> BulkResult:
    return await _bulk(
        db,
        entitlement_ids,
        lambda eid: match_entitlement(
            db,
            eid,
            series_id=series_id,
            commands=commands,
            matched_via=matched_via,
        ),
    )


async def accept_entitlement(
    db,
    settings,
    entitlement_id: int,
    *,
    commands=None,
    factory=None,
    root_folder_id: int | None = None,
    matched_via: str,
) -> SourceEntitlementRow:
    """Apply an entitlement's OWN stored proposal (FRG-SRC-011).

    The server-side form of what the review screen used to do client-side: read
    the row's proposal and route it to the action it describes —

    * a ``library``-kind proposal (or a bare ``proposed_series_id``) →
      :func:`match_entitlement` against that series;
    * a ``comicvine``-kind proposal → :func:`add_entitlement` with that volume
      id, which itself degrades to a match when the volume is already in the
      library and sweeps the siblings (FRG-SRC-008).

    A row with no usable proposal is a 422 :class:`EntitlementActionError` — in
    a bulk run that lands as THAT row's per-row error, never a failure of the
    whole request (there is nothing to fall back to: forcing another row's
    target is precisely what accept-each-own-proposal exists to prevent).

    **The proposal is read here, at the row's turn**, not from a caller-held
    snapshot. That is load-bearing for the same-title group case: accepting the
    first row of a group whose rows all propose the same not-yet-in-library
    volume runs the add, whose FRG-SRC-008 sweep rewrites the siblings'
    proposals into library matches — so the siblings, re-read at their own turn,
    match into the new series instead of re-adding it.

    **Only a row still in review (``new``) is acceptable** (FRG-SRC-011). Accept
    applies a row's *proposal*, and a proposal is the automatic matcher's
    suggestion for an undecided row — it is not a mandate over a decision the
    operator already made. Without this, a bulk accept over a selection that
    happens to include ignored rows (a "select all in bundle" after some
    ignores, a stale selection) silently reversed those ignores: the row flipped
    ignored → matched and its source-grab was enqueued, downloading exactly the
    item the operator had withdrawn. Both refusals are per-ROW
    (:func:`_accept_precondition_error`), so the rest of the batch still runs,
    and the authoritative re-read happens inside the write transaction
    (``require_new=True``) so a concurrent ignore cannot slip through the gap.
    """
    row = await _reload(db, entitlement_id)
    if row is None:
        raise EntitlementActionError(
            f"entitlement {entitlement_id} not found", status=404
        )
    refusal = _accept_precondition_error(entitlement_id, row.review_status)
    if refusal is not None:
        raise refusal
    series_id = _proposed_series_id(row)
    if series_id is not None:
        return await match_entitlement(
            db,
            entitlement_id,
            series_id=series_id,
            commands=commands,
            matched_via=matched_via,
            require_new=True,
        )
    cvid = _proposed_cv_id(row)
    if cvid is not None:
        return await add_entitlement(
            db,
            settings,
            entitlement_id,
            commands=commands,
            factory=factory,
            root_folder_id=root_folder_id,
            cv_volume_id=cvid,
            matched_via=matched_via,
            require_new=True,
        )
    raise EntitlementActionError(
        f"entitlement {entitlement_id} has no proposed match to accept — "
        "search for a series on the row instead",
        status=422,
    )


async def bulk_accept(
    db,
    settings,
    entitlement_ids: list[int],
    *,
    commands=None,
    factory=None,
    root_folder_id: int | None = None,
    matched_via: str,
) -> BulkResult:
    """Accept each row's OWN proposal, one per-row transaction (FRG-SRC-011).

    Heterogeneous by construction: some rows match, some add, and a row that
    cannot be accepted contributes an error entry while every other row still
    runs (the shared :func:`_bulk` idiom).
    """
    return await _bulk(
        db,
        entitlement_ids,
        lambda eid: accept_entitlement(
            db,
            settings,
            eid,
            commands=commands,
            factory=factory,
            root_folder_id=root_folder_id,
            matched_via=matched_via,
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


async def _series_id_for_volume(db, cv_volume_id: int) -> int | None:
    """The library series id holding ``cv_volume_id``, or ``None`` (FRG-SRC-008).

    The same uniqueness the add flow enforces (``add_series`` rejects a volume
    that is already in the library), read BEFORE the add so the review action can
    degrade to a match instead of surfacing that rejection to the operator."""
    from sqlalchemy import select

    from foragerr.library.models import SeriesRow

    async with db.read_session() as session:
        return await session.scalar(
            select(SeriesRow.id).where(SeriesRow.cv_volume_id == cv_volume_id)
        )


async def _reresolve_sibling_proposals(
    db,
    *,
    cv_volume_id: int,
    series_id: int,
    series_title: str | None,
    exclude_entitlement_id: int,
) -> int:
    """Point still-in-review proposals of the just-added volume at the new series.

    A store order routinely yields several entitlements for one volume (an issue
    run, a bundle re-purchase, a CBZ/PDF twin). Their proposals were computed as
    ComicVine *adds* against ``cv_volume_id``; once the add has created the
    series, an add on any of them would fail as "already in the library" — so
    each is rewritten in place into a ``library``-kind MATCH proposal targeting
    the new series (FRG-SRC-008), with ``proposed_series_id`` set so a single
    click matches.

    Scope guarantees:

    * only ``review_status = "new"`` rows are touched — a matched or ignored row
      is an operator decision and is never overwritten;
    * the acting entitlement is excluded (its own link is written by the
      following :func:`match_entitlement`);
    * the ranked ``candidates`` list is preserved verbatim (the UI still offers
      the alternatives) and ``auto`` is forced ``False`` — a rewrite is a
      *convenience*, never a licence for the auto-sync path to accept without
      review.

    Runs as ONE write transaction, so the whole sibling set moves together.
    Returns the number of rows rewritten.

    **The volume filter is pushed into SQL** (``json_extract`` on the stored
    proposal). Selecting every ``new`` row with a proposal and filtering in
    Python meant the sweep loaded and JSON-parsed the entire review queue for
    each accept — measured at 19.7 ms per add against 1,300 rows, INSIDE the
    writer lock, so a 500-row bulk accept spent ~10 s serializing every other
    writer behind it. The predicate is exact (the same key the Python filter
    read), so the row set is unchanged; ``json_extract`` is available on every
    SQLite build we ship against, and the residual Python check below stays as
    the correctness guard.
    """
    import json

    from sqlalchemy import func, select

    rewritten = 0
    async with db.write_session() as session:
        rows = (
            (
                await session.execute(
                    select(SourceEntitlementRow).where(
                        SourceEntitlementRow.review_status == "new",
                        SourceEntitlementRow.id != exclude_entitlement_id,
                        SourceEntitlementRow.proposed_match_json.is_not(None),
                        func.json_extract(
                            SourceEntitlementRow.proposed_match_json,
                            "$.cv_volume_id",
                        )
                        == cv_volume_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        now = utcnow()
        for row in rows:
            data = _loads_proposal(row.proposed_match_json)
            if data is None or data.get("cv_volume_id") != cv_volume_id:
                continue
            if data.get("kind") == "library" and data.get("series_id") == series_id:
                continue  # already resolved (a re-run) — leave it alone
            data.update(
                {
                    "kind": "library",
                    "series_id": series_id,
                    "title": series_title or data.get("title"),
                    "auto": False,
                }
            )
            row.proposed_match_json = json.dumps(data, sort_keys=True)
            row.proposed_series_id = series_id
            row.updated_at = now
            rewritten += 1
    if rewritten:
        logger.info(
            "sources.review: re-resolved %d sibling proposal(s) for cv volume %d "
            "onto series %d",
            rewritten,
            cv_volume_id,
            series_id,
        )
    return rewritten


def _loads_proposal(raw: str | None) -> dict | None:
    """A stored proposal as a dict, or ``None`` when absent/unparseable."""
    import json

    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _proposed_cv_id(row: SourceEntitlementRow) -> int | None:
    """The ComicVine volume id from a stored proposal, if it is a CV proposal."""
    data = _loads_proposal(row.proposed_match_json)
    if data is None:
        return None
    cvid = data.get("cv_volume_id")
    return cvid if isinstance(cvid, int) else None


def _proposed_series_id(row: SourceEntitlementRow) -> int | None:
    """The library series a stored proposal points at, if it is a match proposal.

    The JSON is authoritative (the FRG-SRC-008 sweep rewrites ``kind`` and
    ``series_id`` together); the denormalized ``proposed_series_id`` column is
    the fallback for a row whose JSON is absent or unparseable. ``None`` for a
    ComicVine-kind proposal — that one is an add, not a match — and ``None`` for
    a VERDICT marker (FRG-SRC-010): "we looked, there is nothing plausible" is a
    parsed, authoritative answer, so falling through to the denormalized column
    would resurrect a stale series id the marker deliberately replaced and
    accept the row against it. Fail-open on a row whose whole point is that
    there is nothing to accept."""
    data = _loads_proposal(row.proposed_match_json)
    if data is not None and data.get("verdict"):
        return None
    if data is not None and data.get("kind") == "library":
        series_id = data.get("series_id")
        if isinstance(series_id, int):
            return series_id
        return None
    if data is not None and data.get("kind") == "comicvine":
        return None
    column = row.proposed_series_id
    return column if isinstance(column, int) else None


async def _reload(db, entitlement_id: int) -> SourceEntitlementRow | None:
    from foragerr.sources.repo import get_entitlement

    return await get_entitlement(db, entitlement_id)


__all__ = [
    "BulkResult",
    "EntitlementActionError",
    "accept_entitlement",
    "add_entitlement",
    "bulk_accept",
    "bulk_ignore",
    "bulk_match",
    "bulk_restore",
    "ignore_entitlement",
    "match_entitlement",
    "restore_entitlement",
    "retry_download",
]
