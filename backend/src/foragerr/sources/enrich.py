"""Post-sync proposal computation + the opt-in auto-sync path (FRG-SRC-004).

Run after a source sync (from the ``source-sync`` command handler): compute a
server proposed match for every ``new`` comic entitlement that lacks one, then —
only when the per-source ``auto_sync`` toggle is ON — auto-accept and download
the confidently matched ones. Kept out of ``run_sync`` itself so the diff stays
CV-free and A1's sync tests are untouched (proposals are a separate enrichment
pass with its own CV budget handling).

CV politeness / budget (FRG-META-016): one :class:`ComicVineClient` is reused
across the batch and consulted only when no library match wins; a
:class:`ComicVineBudgetExhausted` stops the CV arm for this run (remaining items
keep a NULL proposal and are retried next sync). ComicVine is used at all only
when an api key is configured, so an unconfigured deployment (and the test
suite) never issues a CV call.
"""

from __future__ import annotations

import logging

from foragerr.db.base import utcnow
from foragerr.metadata.errors import ComicVineBudgetExhausted
from foragerr.sources import repo, review
from foragerr.sources.matching import (
    AUTO_MATCH_THRESHOLD,
    LibrarySeriesLite,
    ProposedMatch,
    compute_proposed_match,
)
from foragerr.sources.models import SourceEntitlementRow

logger = logging.getLogger("foragerr.sources.enrich")


async def _load_library(db) -> list[LibrarySeriesLite]:
    from foragerr.library import repo as library_repo

    async with db.read_session() as session:
        series = await library_repo.list_series(session)
    return [
        LibrarySeriesLite(id=s.id, title=s.title, start_year=s.start_year)
        for s in series
    ]


def _build_cv_client(settings):
    """A live ComicVine client when an api key is configured, else ``None``."""
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
        cv_client = _build_cv_client(settings)

    proposals: dict[int, ProposedMatch] = {}
    try:
        budget_hit = False
        for ent in pending:
            client = None if budget_hit else cv_client
            try:
                proposal = await compute_proposed_match(
                    human_name=ent.human_name, library=library, cv_client=client
                )
            except ComicVineBudgetExhausted:
                # Defer this and the rest of the CV arm; leave NULL (retry later).
                budget_hit = True
                proposal = await compute_proposed_match(
                    human_name=ent.human_name, library=library, cv_client=None
                )
            if proposal is not None:
                proposals[ent.id] = proposal
    finally:
        if owns_client and cv_client is not None:
            await cv_client.aclose()

    await _persist_proposals(db, proposals)

    accepted = 0
    if source.auto_sync:
        accepted = await _auto_accept(
            db, settings, proposals, commands=commands
        )
    return (
        f"enrich: {len(proposals)}/{len(pending)} proposed, "
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
    db, settings, proposals: dict[int, ProposedMatch], *, commands
) -> int:
    """Auto-accept + download confidently matched new items (FRG-SRC-004).

    Only fires when the source toggle is ON (caller-gated). A library proposal
    links to the existing series; a ComicVine proposal runs the add flow. Both
    queue the grab. Below-threshold items are left in review.
    """
    accepted = 0
    for eid, proposal in proposals.items():
        if proposal.confidence < AUTO_MATCH_THRESHOLD:
            continue
        try:
            if proposal.best.kind == "library" and proposal.best.series_id:
                await review.match_entitlement(
                    db, eid, series_id=proposal.best.series_id, commands=commands
                )
            elif proposal.best.kind == "comicvine" and proposal.best.cv_volume_id:
                await review.add_entitlement(
                    db,
                    settings,
                    eid,
                    commands=commands,
                    cv_volume_id=proposal.best.cv_volume_id,
                )
            else:
                continue
            accepted += 1
        except review.EntitlementActionError as exc:
            logger.warning("auto-sync: entitlement %s not accepted: %s", eid, exc)
    return accepted


__all__ = ["enrich_source"]
