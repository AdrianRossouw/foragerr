"""Post-sync proposal computation + the opt-in auto-sync path (FRG-SRC-004).

Run after a source sync (from the ``source-sync`` command handler): compute a
server proposed match for every ``new`` comic entitlement that lacks one, then —
only when the per-source ``auto_sync`` toggle is ON — auto-accept and download
the confidently matched ones. Kept out of ``run_sync`` itself so the diff stays
CV-free and A1's sync tests are untouched (proposals are a separate enrichment
pass with its own CV budget handling).

CV politeness / budget (FRG-META-016): one :class:`ComicVineClient` is reused
across the batch; a :class:`ComicVineBudgetExhausted` ENDS the enrichment run.
Every item from the exhausting one onward keeps a NULL proposal and is retried
next sync — no library-only fallback is computed, persisted or auto-accepted in
a budget-hit window (FRG-SRC-010: "budget exhaustion SHALL leave affected rows
un-proposed and retryable"). A fallback proposal there would be a shelf-local
guess written under a CV-shaped promise, it would clear the item out of the
pending set forever, and — at ``auto_sync`` ON — could accept and download
against it.

ComicVine is used at all only when an api key is configured, so an unconfigured
deployment (and the test suite) never issues a CV call. That no-key deployment
is the ONLY place the ``library-fallback`` universe may legitimately be
produced; a fallback proposal appearing on a CV-configured run is refused by the
auto-accept path outright (see :func:`_auto_accept`).

Rows whose computation RAN and found nothing plausible are stamped with the
explicit no-plausible-match marker (FRG-SRC-010) rather than left NULL, so the
review UI can tell "we looked, there is nothing" from "not looked at yet". Only
deferrals — a budget hit, or a ComicVine call that failed — leave a row NULL.
"""

from __future__ import annotations

import logging

from foragerr.db.base import utcnow
from foragerr.metadata.errors import ComicVineBudgetExhausted
from foragerr.sources import repo, review
from foragerr.sources.matching import (
    AUTO_MATCH_THRESHOLD,
    UNIVERSE_COMICVINE,
    LibrarySeriesLite,
    ProposedMatch,
    compute_proposed_match,
)
from foragerr.sources.models import MATCHED_VIA_AUTO, SourceEntitlementRow

logger = logging.getLogger("foragerr.sources.enrich")


async def _load_library(db) -> list[LibrarySeriesLite]:
    from foragerr.library import repo as library_repo

    async with db.read_session() as session:
        series = await library_repo.list_series(session)
    # ``cv_volume_id`` is what makes the library an OVERLAY on the ComicVine
    # matching universe (FRG-SRC-010): a CV candidate already in the library is
    # proposed as a match, not an add. It is NOT NULL on every series row.
    return [
        LibrarySeriesLite(
            id=s.id,
            title=s.title,
            start_year=s.start_year,
            cv_volume_id=s.cv_volume_id,
        )
        for s in series
    ]


def build_cv_client(settings):
    """A live ComicVine client when an api key is configured, else ``None``.

    Public because the operator-initiated restore endpoints need the same
    "is ComicVine available to this deployment at all?" answer, and a second
    copy of the key check would be a second place to get it wrong."""
    try:
        key = settings.comicvine_api_key.get_secret_value()
    except Exception:  # noqa: BLE001 — a missing/odd key means "no CV"
        return None
    if not key.strip():
        return None
    from foragerr.library.flows._common import comicvine_factory
    from foragerr.metadata.comicvine import ComicVineClient

    return ComicVineClient(settings, comicvine_factory(settings))


async def enrich_source(db, settings, source, *, commands=None, cv_client=None) -> str:
    """Compute proposals for a source's un-proposed new comics, then auto-sync.

    Returns a one-line summary. ``cv_client`` may be injected (tests); otherwise
    a client is built only when CV is configured, and always closed.
    """
    pending = [
        e
        for e in await repo.list_entitlements(
            db, source.id, classification="comic", review_status="new"
        )
        if e.proposed_match_json is None
    ]
    library = await _load_library(db)

    owns_client = cv_client is None
    if cv_client is None:
        cv_client = build_cv_client(settings)
    # Captured before the ``finally`` closes/clears the client: was ComicVine
    # available to THIS run at all? It decides whether a ``library-fallback``
    # proposal is the honest no-key degradation or a stand-in for a CV call that
    # should have happened — see :func:`_auto_accept`.
    cv_configured = cv_client is not None

    proposals: dict[int, ProposedMatch] = {}
    deferred = 0
    try:
        for index, ent in enumerate(pending):
            try:
                proposal = await compute_proposed_match(
                    human_name=ent.human_name, library=library, cv_client=cv_client
                )
            except ComicVineBudgetExhausted as exc:
                # The CV budget is a per-run wall, not a per-item one: stop the
                # batch here. This item and every remaining one keep a NULL
                # proposal and are retried on the next sync (FRG-SRC-010).
                # Nothing library-only is computed in its place — a fallback
                # proposal would freeze the row out of the pending set and could
                # be auto-accepted, which is precisely what deferral prevents.
                deferred = len(pending) - index
                logger.info(
                    "enrich: ComicVine budget exhausted (%s); %d item(s) left "
                    "un-proposed and retryable",
                    exc,
                    deferred,
                )
                break
            if proposal is None:
                # CV was consulted and could not answer: no verdict exists, so
                # the row stays NULL/retryable rather than recording one.
                continue
            proposals[ent.id] = proposal
    finally:
        if owns_client and cv_client is not None:
            await cv_client.aclose()

    await _persist_proposals(db, proposals)

    accepted = 0
    if source.auto_sync:
        accepted = await _auto_accept(
            db, settings, proposals, commands=commands, cv_configured=cv_configured
        )
    matched = sum(1 for p in proposals.values() if not p.is_no_match)
    return (
        f"enrich: {matched}/{len(pending)} proposed, "
        f"{len(proposals) - matched} no-match, {deferred} deferred, "
        f"{accepted} auto-accepted (auto_sync={'on' if source.auto_sync else 'off'})"
    )


async def _persist_proposals(db, proposals: dict[int, ProposedMatch]) -> None:
    if not proposals:
        return
    now = utcnow()
    async with db.write_session() as session:
        for eid, proposal in proposals.items():
            row = await session.get(SourceEntitlementRow, eid)
            # Only stamp a still-new, still-unproposed item — never clobber an
            # operator decision that landed between the read and this write.
            if row is None or row.review_status != "new" or row.proposed_match_json:
                continue
            row.proposed_series_id = proposal.proposed_series_id
            row.proposed_match_json = proposal.to_json()
            row.updated_at = now


async def _auto_accept(
    db,
    settings,
    proposals: dict[int, ProposedMatch],
    *,
    commands,
    cv_configured: bool,
) -> int:
    """Auto-accept + download confidently matched new items (FRG-SRC-004).

    Only fires when the source toggle is ON (caller-gated). A library proposal
    links to the existing series; a ComicVine proposal runs the add flow. Both
    queue the grab. Below-threshold items are left in review.

    Two shapes are refused outright, whatever their confidence:

    * a no-plausible-match marker — there is nothing to accept;
    * a ``library-fallback`` proposal produced on a run where ComicVine WAS
      configured (``cv_configured``). On such a run the fallback universe can
      only mean a CV call stood in for, not made — the budget-hit hazard — and a
      shelf-local guess wearing a catalog-shaped promise must never
      accept-and-download unreviewed. (After the deferral fix the batch stops at
      the budget wall, so this branch is unreachable by construction; it is the
      belt to that braces.) A genuinely unconfigured deployment still
      auto-accepts its confident library matches — that is the honest
      degradation FRG-SRC-010 specifies, not a stand-in.

    Every acceptance here is stamped ``matched_via = "auto"`` (FRG-PP-022 guard
    3): no human chose these series, so the import pipeline's ordinal fallback
    ("Vol. N" → issue N) is withheld from them — a bare ``Vol. N`` store title
    clears the auto-match threshold easily, and that must not become a no-human
    route into an ordinal-derived issue mapping.

    **The review state is re-read per row, inside the loop.** ``proposals`` is a
    snapshot taken before the (potentially long) persist + accept run, and the
    operator is looking at the same queue: a row ignored or matched by hand
    while the loop is working is a decision, and auto-sync must not walk over it
    with a proposal computed before that decision existed. ``accept_entitlement``
    is not the seam here — auto-sync calls match/add directly — so the check
    lives here; the authoritative in-transaction guard remains ``_queue_grab``'s
    ``matched`` re-read.
    """
    accepted = 0
    for eid, proposal in proposals.items():
        if proposal.best is None:
            continue
        current = await repo.get_entitlement(db, eid)
        if current is None or current.review_status != "new":
            continue  # decided by the operator mid-run — never overwrite it
        if cv_configured and proposal.universe != UNIVERSE_COMICVINE:
            logger.warning(
                "auto-sync: refusing entitlement %s — %s proposal on a "
                "ComicVine-configured run is never auto-acceptable",
                eid,
                proposal.universe,
            )
            continue
        if proposal.confidence < AUTO_MATCH_THRESHOLD:
            continue
        try:
            if proposal.best.kind == "library" and proposal.best.series_id:
                await review.match_entitlement(
                    db,
                    eid,
                    series_id=proposal.best.series_id,
                    commands=commands,
                    matched_via=MATCHED_VIA_AUTO,
                    # The mid-run status pre-check above is a TOCTOU on its
                    # own: only the write-transaction re-read can make an
                    # operator decision landed between read and write win.
                    require_new=True,
                )
            elif proposal.best.kind == "comicvine" and proposal.best.cv_volume_id:
                await review.add_entitlement(
                    db,
                    settings,
                    eid,
                    commands=commands,
                    cv_volume_id=proposal.best.cv_volume_id,
                    matched_via=MATCHED_VIA_AUTO,
                    require_new=True,
                )
            else:
                continue
            accepted += 1
        except review.EntitlementActionError as exc:
            logger.warning("auto-sync: entitlement %s not accepted: %s", eid, exc)
    return accepted


__all__ = ["build_cv_client", "enrich_source"]
