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

Frugality (FRG-SRC-013). A run is bounded by a budget it does not control, so
the order it works in decides whether the queue CONVERGES. Every row a run
touches is stamped ``proposal_attempted_at`` — proposed, marked, deferred at the
budget wall, or errored alike — and the pending set is walked
never-attempted-first then oldest-attempt-first. A failing or deferred head
therefore moves behind the rows it did not reach, so it can only ever delay its
OWN retry; before this, an oldest-id-first walk restarted at the same doomed
rows every night and the tail was never seen at all. Rows whose ComicVine
consultation ERRORED additionally wait out
``comicvine_error_retry_spacing_seconds`` on this scheduled path. The three
operator-initiated paths — restore, the review row's per-row search, and the
bulk recompute — ignore the spacing entirely, because the operator asking IS the
retry decision. (Manual "Sync now" is NOT one of them: it runs the same
scheduled command, so it spaces exactly as the nightly run does.) The stamps
order work and nothing else: a budget-deferred row still has a NULL proposal and
is still eligible, exactly as FRG-SRC-010 requires.

Two revisit shapes rejoin the pending set rather than staying frozen:
``library-fallback`` proposals once a ComicVine key IS configured (they were
computed catalog-blind — verdicts and guesses about the shelf, not the catalog),
and — through the operator-triggered :func:`recompute_proposals` — proposals
stored before the CV-first universe existed.
"""

from __future__ import annotations

import datetime as dt
import json
import logging

from foragerr.db.base import utcnow
from foragerr.metadata.errors import ComicVineBudgetExhausted
from foragerr.sources import repo, review
from foragerr.sources.matching import (
    AUTO_MATCH_THRESHOLD,
    UNIVERSE_COMICVINE,
    UNIVERSE_LIBRARY_FALLBACK,
    VERDICT_NO_PLAUSIBLE_MATCH,
    LibrarySeriesLite,
    ProposedMatch,
    compute_proposed_match,
)
from foragerr.sources.models import MATCHED_VIA_AUTO

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


def comicvine_configured(settings) -> bool:
    """Whether this deployment has a usable ComicVine key at all.

    The ONE key check every "is ComicVine available here?" caller shares — the
    client builder below, and the surfaces that must answer the question WITHOUT
    paying for a client (an endpoint deciding whether a ComicVine-only action is
    even runnable). A second copy would be a second place to get it wrong."""
    try:
        key = settings.comicvine_api_key.get_secret_value()
    except Exception:  # noqa: BLE001 — a missing/odd key means "no CV"
        return False
    return bool(key.strip())


def build_cv_client(settings, *, lane: str = "batch"):
    """A live ComicVine client when an api key is configured, else ``None``.

    Public because the operator-initiated restore endpoints need the same
    "is ComicVine available to this deployment at all?" answer, and a second
    copy of the key check would be a second place to get it wrong.

    ``lane`` (FRG-META-022) defaults to ``batch`` — this function's own callers
    are the nightly enrichment run — and the operator-initiated endpoints pass
    ``interactive`` so an exhausted batch share never blocks the person waiting
    at the review screen."""
    if not comicvine_configured(settings):
        return None
    from foragerr.library.flows._common import comicvine_factory
    from foragerr.metadata.comicvine import ComicVineClient

    return ComicVineClient(settings, comicvine_factory(settings), lane=lane)


def _proposal_data(raw: str | None) -> dict | None:
    """The stored proposal JSON as a dict, or ``None`` when absent/unreadable."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_library_fallback(raw: str | None) -> bool:
    """True for ANY proposal computed WITHOUT ComicVine (FRG-SRC-013).

    The universe alone is the signature, because the whole stored proposal — a
    no-match marker AND a ranked best guess — was produced against the local
    shelf rather than the catalog. Both are answers to a question the review
    screen does not ask, and both are non-NULL, so both freeze the row out of
    every later pass. Once a key exists the row deserves a catalog answer and
    rejoins the pending set.

    Keying on the verdict as well would have covered only half the keyless era:
    a shelf-ranked BEST (universe ``library-fallback`` with a candidate) is the
    more consequential half — it is what the review screen renders as a
    proposal — and it would have been the one shape neither revisit path could
    reach. A proposal computed WITH ComicVine is a real answer and stays put.
    """
    data = _proposal_data(raw)
    return bool(data and data.get("universe") == UNIVERSE_LIBRARY_FALLBACK)


def is_marker(raw: str | None) -> bool:
    """True for any stored no-plausible-match marker (FRG-SRC-010)."""
    data = _proposal_data(raw)
    return bool(data and data.get("verdict") == VERDICT_NO_PLAUSIBLE_MATCH)


def predates_cv_universe(raw: str | None) -> bool:
    """True for a stored proposal written before the ComicVine-first universe.

    ``universe`` is the signature: it was added with the CV-first ranking
    (FRG-SRC-010), so a stored proposal LACKING the key was ranked against the
    local library alone, whatever it claims. That absence is what the bulk
    recompute targets — it cannot be inferred from the value of any other field.

    A stored value that will not parse counts as pre-universe too. It is
    non-NULL, so the enrichment pass skips it forever; it has no readable
    universe, so no other predicate claims it; and it renders as nothing on the
    review screen. Recomputing it is the only way it can ever become a proposal
    again, and the cost of being wrong is one ComicVine call. Only a genuinely
    absent proposal (``None``/empty) stays the enrichment pass's business.
    """
    if not raw:
        return False
    data = _proposal_data(raw)
    if data is None:
        return True
    return "universe" not in data


def _error_spacing_blocked(row, *, now: dt.datetime, spacing_seconds: int) -> bool:
    """True while an ERRORED row is still inside its re-attempt spacing.

    Only errors are spaced. A row deferred at the budget wall carries a stamp
    too, but its computation never ran — spacing it would turn a rolling-window
    refusal into a day-long freeze, which is the opposite of frugal.
    """
    if spacing_seconds <= 0 or not row.proposal_attempt_error:
        return False
    attempted = row.proposal_attempted_at
    if attempted is None:
        return False
    return (now - attempted) < dt.timedelta(seconds=spacing_seconds)


def eligible_for_enrichment(row, *, cv_configured: bool) -> bool:
    """Whether a ``new`` comic row still WANTS a proposal (FRG-SRC-013).

    Eligibility is a property of the stored proposal, never of an attempt stamp:

    * a NULL proposal — never computed, or deferred/errored last time
      (FRG-SRC-010: a deferral leaves the row eligible, and no stamp changes
      that);
    * ANY ``library-fallback`` proposal on a run where ComicVine IS configured —
      marker or shelf-ranked best alike, the keyless answer a key has now made
      answerable. Not just the marker: a keyless run that DID find a shelf
      candidate stored it as a fallback best, and gating on the no-match verdict
      left exactly those rows — the ones showing the operator a proposal — frozen
      on a keyed deployment.
    """
    if row.proposed_match_json is None:
        return True
    return cv_configured and is_library_fallback(row.proposed_match_json)


def select_pending(
    rows,
    *,
    cv_configured: bool,
    now: dt.datetime,
    spacing_seconds: int,
) -> tuple[list, int]:
    """``(pending, spaced)`` for a scheduled enrichment pass.

    ``rows`` arrives already in work order — never-attempted-first then
    oldest-attempt-first (``repo.list_entitlements(order_by_attempt=True)``) —
    so this only decides membership: the eligible rows, minus those still inside
    their error spacing (counted, never silently dropped).
    """
    eligible = [
        row for row in rows if eligible_for_enrichment(row, cv_configured=cv_configured)
    ]
    pending = [
        row
        for row in eligible
        if not _error_spacing_blocked(row, now=now, spacing_seconds=spacing_seconds)
    ]
    return pending, len(eligible) - len(pending)


def _spacing_seconds(settings) -> int:
    return int(getattr(settings, "comicvine_error_retry_spacing_seconds", 0) or 0)


async def enrich_source(db, settings, source, *, commands=None, cv_client=None) -> str:
    """Compute proposals for a source's un-proposed new comics, then auto-sync.

    Returns a one-line summary. ``cv_client`` may be injected (tests); otherwise
    a client is built only when CV is configured, and always closed.

    The client is built FIRST because the pending set depends on it: whether a
    ``library-fallback`` marker is a frozen keyless verdict (revisit it) or the
    honest answer of an unconfigured deployment (leave it) is decided by whether
    ComicVine is available to this run.
    """
    owns_client = cv_client is None
    if cv_client is None:
        cv_client = build_cv_client(settings)
    # Captured before the ``finally`` closes/clears the client: was ComicVine
    # available to THIS run at all? It decides whether a ``library-fallback``
    # proposal is the honest no-key degradation or a stand-in for a CV call that
    # should have happened — see :func:`_auto_accept`.
    cv_configured = cv_client is not None

    proposals: dict[int, ProposedMatch] = {}
    attempts: dict[int, repo.ProposalAttempt] = {}
    deferred = 0
    try:
        candidates = await repo.list_entitlements(
            db,
            source.id,
            classification="comic",
            review_status="new",
            order_by_attempt=True,
        )
        pending, spaced = select_pending(
            candidates,
            cv_configured=cv_configured,
            now=utcnow(),
            spacing_seconds=_spacing_seconds(settings),
        )
        library = await _load_library(db)

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
                #
                # The row the wall stopped ON is still stamped (attempted, not
                # errored): that is what advances the next run's starting point
                # past the prefix this run got through, instead of grinding the
                # same head every night. Rows it never reached keep a NULL stamp
                # and therefore sort FIRST next time.
                attempts[ent.id] = repo.ProposalAttempt()
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
                # the row stays NULL/retryable rather than recording one — and
                # the error is recorded so the spacing can hold it back next run.
                attempts[ent.id] = repo.ProposalAttempt(errored=True)
                continue
            proposals[ent.id] = proposal
            attempts[ent.id] = repo.ProposalAttempt(
                proposed_series_id=proposal.proposed_series_id,
                proposed_match_json=proposal.to_json(),
                store=True,
                # Compare-and-swap against what this pass READ: NULL for the
                # ordinary case, the stale marker for a fallback revisit.
                expect_json=ent.proposed_match_json,
            )
    finally:
        if owns_client and cv_client is not None:
            await cv_client.aclose()

    await repo.record_proposal_attempts(db, attempts)

    accepted = 0
    if source.auto_sync:
        accepted = await _auto_accept(
            db, settings, proposals, commands=commands, cv_configured=cv_configured
        )
    matched = sum(1 for p in proposals.values() if not p.is_no_match)
    spacing_note = f", {spaced} spaced" if spaced > 0 else ""
    return (
        f"enrich: {matched}/{len(pending)} proposed, "
        f"{len(proposals) - matched} no-match, {deferred} deferred{spacing_note}, "
        f"{accepted} auto-accepted (auto_sync={'on' if source.auto_sync else 'off'})"
    )


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
    with a proposal computed before that decision existed. The CLASSIFICATION is
    re-read on the same terms (FRG-SRC-016): a row marked non-comic mid-run is
    still ``new``, so the review-state check alone would let auto-sync match it
    — and a matched row refuses the mark, leaving the operator's correction
    un-editable behind an "already matched" it never asked for.
    ``accept_entitlement`` is not the seam here — auto-sync calls match/add
    directly — so the check lives here; the authoritative in-transaction guard
    remains ``_queue_grab``'s ``matched`` re-read.
    """
    accepted = 0
    for eid, proposal in proposals.items():
        if proposal.best is None:
            continue
        current = await repo.get_entitlement(db, eid)
        if current is None or current.review_status != "new":
            continue  # decided by the operator mid-run — never overwrite it
        if current.classification != "comic":
            continue  # marked non-comic mid-run (FRG-SRC-016) — not a comic
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
                    # Unattended: no operator is reviewing, so the sibling
                    # proposal sweep would be pure churn — and running it per
                    # auto-accepted row is O(queue) work times the queue size.
                    sweep_group=False,
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
                    sweep_group=False,  # unattended — see the match branch above
                    # Nobody is waiting on an auto-accept: it runs from the
                    # nightly enrichment batch, and the add's ComicVine
                    # existence check must be capped at the batch share like
                    # the rest of it (FRG-META-022). Left interactive, a
                    # 1,318-item auto-sync would spend the reserve that exists
                    # to keep the operator's own searches answering.
                    lane="batch",
                )
            else:
                continue
            accepted += 1
        except review.EntitlementActionError as exc:
            logger.warning("auto-sync: entitlement %s not accepted: %s", eid, exc)
    return accepted


def is_recompute_target(row, *, include_markers: bool) -> bool:
    """Whether the bulk recompute should refresh this row's stored proposal.

    A row with NO stored proposal is a target — the same rows the enrichment
    pass owns. Enrichment only runs POST-SYNC, so on a daily-sync deployment
    "un-proposed" is a state an operator can otherwise only leave by waiting;
    and the deferred bulk restore (FRG-SRC-004) creates that state deliberately,
    in bulk, at the moment the operator is looking at the queue. Recompute is
    the lever that fills it. The double-spend this exclusion once guarded
    against does not arise: the two passes take the same work order and
    ``record_proposal_attempts`` stamps every attempt, so whichever runs second
    finds the prefix already proposed.

    The rest of what recompute exists for is the proposal that is STORED and
    stale:

    * one written before the ComicVine-first universe (no ``universe`` key —
      library-ranked whatever it looks like), the v0.11.0 upgrade gap;
    * one written IN the ``library-fallback`` universe — the same gap one
      version later. A keyless deployment's proposals are shelf-ranked for
      exactly the reason a pre-universe one is, and this walk cannot run at all
      without a key (see :func:`recompute_proposals`), so reaching them here is
      unconditional rather than an opt-in. Without it, a deployment that added
      its key AFTER a keyless sync had a class of rows no revisit path could
      touch;
    * on explicit opt-in, a ComicVine no-plausible-match marker — the operator
      saying "look again", e.g. after the library or the catalog moved. Opt-in
      because re-asking ComicVine about every real verdict is exactly the kind
      of unprompted spend this change exists to stop.
    """
    raw = row.proposed_match_json
    if raw is None:
        return True
    if predates_cv_universe(raw) or is_library_fallback(raw):
        return True
    return include_markers and is_marker(raw)


async def recompute_proposals(
    db, settings, source, *, include_markers: bool = False, cv_client=None
) -> str:
    """Propose for one source's un-proposed and stale ``new`` rows, resumably
    (FRG-SRC-013).

    The operator-triggered half of the frugality work (design D6). It walks
    ``new`` rows only — a matched or ignored row is a DECISION and is never
    recomputed (FRG-SRC-008/012 stickiness) — in the D5 attempt order, writing
    each target's proposal and stamping the attempt. The stamp is what
    makes it resumable: a refreshed row sorts to the back, so a re-run after a
    budget window picks up where this one stopped, with no cursor to persist.

    Stopping is clean by construction. A :class:`ComicVineBudgetExhausted` ends
    the walk with the prefix already refreshed; every row it did not reach KEEPS
    its existing proposal (a stale proposal is still a proposal, and losing it
    would empty the review screen instead of improving it). A per-row ComicVine
    error is recorded and the walk continues — one unanswerable title must not
    end the batch.

    Requires a configured ComicVine key: without one the recomputation could only
    produce ``library-fallback`` rankings, which would REPLACE stale catalog-
    shaped proposals with shelf-local guesses — strictly backwards. It never
    accepts, matches or downloads anything; it only refreshes what the operator
    then reviews.
    """
    owns_client = cv_client is None
    if cv_client is None:
        # Batch lane (FRG-META-022 / design D2), stated explicitly even though it
        # is the default: this is operator-TRIGGERED but not operator-WAITED —
        # a bulk backfill must never eat the reserve that keeps the operator's
        # own interactive searches answering while it runs.
        cv_client = build_cv_client(settings, lane="batch")
    if cv_client is None:
        return (
            "recompute: ComicVine is not configured; nothing recomputed "
            "(a recompute without a catalog could only downgrade proposals)"
        )

    attempts: dict[int, repo.ProposalAttempt] = {}
    errored = 0
    remaining = 0
    exhausted = False
    try:
        candidates = await repo.list_entitlements(
            db,
            source.id,
            classification="comic",
            review_status="new",
            order_by_attempt=True,
        )
        targets = [
            row
            for row in candidates
            if is_recompute_target(row, include_markers=include_markers)
        ]
        library = await _load_library(db)

        for index, ent in enumerate(targets):
            try:
                proposal = await compute_proposed_match(
                    human_name=ent.human_name, library=library, cv_client=cv_client
                )
            except ComicVineBudgetExhausted as exc:
                attempts[ent.id] = repo.ProposalAttempt()
                remaining = len(targets) - index
                exhausted = True
                logger.info(
                    "recompute: ComicVine budget exhausted (%s); %d row(s) keep "
                    "their existing proposal — re-run to resume",
                    exc,
                    remaining,
                )
                break
            if proposal is None:
                attempts[ent.id] = repo.ProposalAttempt(errored=True)
                errored += 1
                continue
            attempts[ent.id] = repo.ProposalAttempt(
                proposed_series_id=proposal.proposed_series_id,
                proposed_match_json=proposal.to_json(),
                store=True,
                # Compare-and-swap on the stale value this walk read: an operator
                # action that rewrote the proposal mid-walk wins.
                expect_json=ent.proposed_match_json,
            )
    finally:
        if owns_client:
            await cv_client.aclose()

    refreshed = await repo.record_proposal_attempts(db, attempts)
    tail = " (budget exhausted; re-run to resume)" if exhausted else ""
    return (
        f"recompute: {refreshed} refreshed, {errored} errored, "
        f"{remaining} remaining{tail}"
    )


__all__ = [
    "build_cv_client",
    "comicvine_configured",
    "eligible_for_enrichment",
    "enrich_source",
    "is_library_fallback",
    "is_marker",
    "is_recompute_target",
    "predates_cv_universe",
    "recompute_proposals",
    "select_pending",
]
