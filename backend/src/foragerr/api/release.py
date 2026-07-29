"""Interactive-search release endpoint (FRG-API-008 / FRG-SRCH-014).

``GET /api/v1/release?issueId=`` runs a live multi-indexer search over the
interactive-enabled indexers and returns EVERY decision — approved, temporarily
rejected, and rejected — each with its verbatim rejection reasons, quality/
format, indexer, size, age, and an ``indexerId``+``guid`` cache key, ordered by
the decision comparator (approved best-first), alongside the additive
per-indexer ``indexers`` outcomes (searched / timed out with its budget /
failed / backing off, FRG-SRCH-015) that make a partial result visibly partial.
The decision set is cached
server-side (~30 min); ``POST /api/v1/release {indexerId, guid}`` grabs from that
cache (enqueuing the inert-until-change-5 grab command) and returns a
deterministic 404-class "search again" error once the entry has expired — never
a silent re-search.

Transport only: the decisions, reasons, and ordering come from the search
pipeline / decision engine; this module shapes HTTP in/out and owns the cache
read/write on the request path.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from foragerr.api.command import CommandResource
from foragerr.api.errors import ApiError
from foragerr.indexers.caps import CapsCache
from foragerr.library.models import IssueRow
from foragerr.providers.backoff import ProviderBackoff
from foragerr.search import Decision
from foragerr.search.titles import to_naive_utc
from foragerr.search_ops import cache_decisions, get_cached, make_indexer_factory, run_search

router = APIRouter(prefix="/release", tags=["release"])


class ReleaseDecisionResource(BaseModel):
    """One decided release row for interactive search (FRG-API-008)."""

    #: The (indexerId, guid) cache key a grab references.
    indexer_id: int
    guid: str
    indexer_name: str
    title: str
    format: str | None
    size_bytes: int | None
    age_seconds: float | None
    #: Format-profile preference rung of this release (higher = better); the
    #: authoritative ordering is the row order (comparator-sorted), this is a
    #: per-row signal for the UI.
    score: int
    outcome: str
    approved: bool
    #: Verbatim, user-visible rejection reasons (empty when approved).
    rejections: list[str]


#: The four honest per-indexer states an interactive search can report
#: (FRG-API-008 / FRG-SRCH-015). ``timed_out`` additionally carries the budget
#: that bounded it, so a partial result is visibly — and machine-readably —
#: partial instead of silently smaller.
OUTCOME_SEARCHED = "searched"
OUTCOME_TIMED_OUT = "timed_out"
OUTCOME_FAILED = "failed"
OUTCOME_BACKING_OFF = "backing_off"


class IndexerOutcomeResource(BaseModel):
    """How one indexer fared in this search (FRG-API-008 / FRG-SRCH-015)."""

    indexer_id: int
    name: str
    #: One of ``searched`` / ``timed_out`` / ``failed`` / ``backing_off``.
    outcome: str
    #: The per-indexer time budget (seconds) that cancelled this indexer; set
    #: only when ``outcome`` is ``timed_out``.
    budget_seconds: float | None = None
    #: How many candidates this indexer contributed before decisioning.
    candidate_count: int = 0


class ReleaseSearchResource(BaseModel):
    """The interactive-search response: decisions plus per-indexer outcomes.

    ``releases`` is the long-standing decision list, comparator-ordered and
    unchanged. ``indexers`` is the additive FRG-SRCH-015 surface: every indexer
    the search selected, with its outcome — so a partial result (one indexer
    timed out) is never mistaken for a complete one.
    """

    releases: list[ReleaseDecisionResource]
    indexers: list[IndexerOutcomeResource]


class ReleaseGrabRequest(BaseModel):
    """Body for ``POST /api/v1/release``: which cached release to grab.

    ``force`` is the sole bypass of the server-side approval gate (FRG-API-008):
    a cached release whose decision was NOT approved is refused unless the
    request deliberately carries ``force: true``, in which case the grab is
    recorded as an operator-forced override.
    """

    indexer_id: int
    guid: str
    force: bool = False


def _factory(request: Request):
    """The outbound factory: an ``app.state.http_factory`` test override wins,
    else the shared indexer factory (mirrors ``api.indexers``)."""
    override = getattr(request.app.state, "http_factory", None)
    if override is not None:
        return override
    return make_indexer_factory(request.app.state.settings)


def _caps_cache(request: Request) -> CapsCache:
    cache = getattr(request.app.state, "caps_cache", None)
    if cache is None:
        cache = CapsCache()
        request.app.state.caps_cache = cache
    return cache


def _row(decision: Decision, profile, now) -> ReleaseDecisionResource:
    candidate = decision.candidate
    fmt = decision.fmt
    age = None
    if candidate.pub_date is not None:
        age = max((to_naive_utc(now) - to_naive_utc(candidate.pub_date)).total_seconds(), 0.0)
    return ReleaseDecisionResource(
        indexer_id=candidate.indexer_id,
        guid=candidate.guid,
        indexer_name=candidate.indexer_name,
        title=candidate.title,
        format=fmt,
        size_bytes=candidate.size_bytes,
        age_seconds=age,
        score=profile.rung(fmt),
        outcome=decision.outcome.value,
        approved=decision.approved,
        rejections=list(decision.reasons),
    )


def _outcome_row(outcome) -> IndexerOutcomeResource:
    """Map one :class:`IndexerSearchOutcome` onto the wire (FRG-API-008).

    Timed out is checked FIRST and is mutually exclusive with a failure by
    construction — the pipeline synthesizes a cancelled indexer's outcome with
    no failure attached, precisely so a slow indexer is never reported (or
    penalized) as a broken one.
    """
    if outcome.timed_out:
        state = OUTCOME_TIMED_OUT
    elif outcome.failure is not None:
        state = OUTCOME_FAILED
    elif outcome.backing_off:
        state = OUTCOME_BACKING_OFF
    else:
        state = OUTCOME_SEARCHED
    return IndexerOutcomeResource(
        indexer_id=outcome.indexer_id,
        name=outcome.indexer_name,
        outcome=state,
        budget_seconds=outcome.time_budget_seconds if outcome.timed_out else None,
        candidate_count=len(outcome.candidates),
    )


@router.get("", response_model=ReleaseSearchResource)
async def search_releases(
    request: Request, issueId: int = Query(..., ge=1)
) -> ReleaseSearchResource:
    """Live interactive search for one issue (FRG-API-008 / FRG-SRCH-014)."""
    db = request.app.state.db
    async with db.read_session() as session:
        issue = await session.get(IssueRow, issueId)
        if issue is None:
            raise ApiError(404, f"issue {issueId} not found")
        series_id = issue.series_id

    result = await run_search(
        db=db,
        settings=request.app.state.settings,
        factory=_factory(request),
        backoff=ProviderBackoff(db),
        caps_cache=_caps_cache(request),
        series_id=series_id,
        issue_id=issueId,
        path="interactive",
    )
    if result is None:  # the issue/series vanished mid-request
        raise ApiError(404, f"issue {issueId} not found")

    # A partial decision set (one indexer timed out) caches and grabs exactly
    # like a complete one — the rows that DID come back are fully decided.
    await cache_decisions(db, issueId, result.decisions)
    return ReleaseSearchResource(
        releases=[_row(d, result.profile, result.now) for d in result.decisions],
        indexers=[_outcome_row(o) for o in result.indexer_outcomes],
    )


@router.post("", status_code=201, response_model=CommandResource)
async def grab_release(body: ReleaseGrabRequest, request: Request) -> CommandResource:
    """Grab a cached release by ``(indexerId, guid)`` (FRG-API-008).

    Cache miss or expiry → a deterministic 404-class "search again" error,
    never a silent re-search, whether or not ``force`` was supplied. On a cache
    hit the server enforces the decision's approved verdict:

    - approved → enqueue the grab (``triggered_by="interactive"``);
    - NOT approved + ``force=False`` → refuse with a typed 409 naming the
      quality-rule constraint, enqueuing nothing;
    - NOT approved + ``force=True`` → enqueue the SAME grab hand-off, recorded
      as an operator-forced override (``triggered_by="interactive-forced"``).
    """
    db = request.app.state.db
    cached = await get_cached(db, body.indexer_id, body.guid)
    if cached is None:
        raise ApiError(
            404,
            "release is no longer cached; run the interactive search again "
            "before grabbing",
        )
    if cached.approved:
        triggered_by = "interactive"
    elif body.force:
        triggered_by = "interactive-forced"
    else:
        raise ApiError(
            409,
            "release was rejected by the quality rules and cannot be grabbed; "
            "re-send with force to override",
        )
    record = await request.app.state.commands.enqueue(
        "grab-release",
        cached.handoff.model_dump(mode="json"),
        triggered_by=triggered_by,
    )
    return CommandResource.from_record(record)
