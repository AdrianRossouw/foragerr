"""Interactive-search release endpoint (FRG-API-008 / FRG-SRCH-014).

``GET /api/v1/release?issueId=`` runs a live multi-indexer search over the
interactive-enabled indexers and returns EVERY decision — approved, temporarily
rejected, and rejected — each with its verbatim rejection reasons, quality/
format, indexer, size, age, and an ``indexerId``+``guid`` cache key, ordered by
the decision comparator (approved best-first). The decision set is cached
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


class ReleaseGrabRequest(BaseModel):
    """Body for ``POST /api/v1/release``: which cached release to grab."""

    indexer_id: int
    guid: str


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


@router.get("", response_model=list[ReleaseDecisionResource])
async def search_releases(
    request: Request, issueId: int = Query(..., ge=1)
) -> list[ReleaseDecisionResource]:
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

    await cache_decisions(db, issueId, result.decisions)
    return [_row(d, result.profile, result.now) for d in result.decisions]


@router.post("", status_code=201, response_model=CommandResource)
async def grab_release(body: ReleaseGrabRequest, request: Request) -> CommandResource:
    """Grab a cached release by ``(indexerId, guid)`` (FRG-API-008).

    Cache hit → enqueue the (inert) grab command and return it. Cache miss or
    expiry → a deterministic 404-class "search again" error, never a silent
    re-search.
    """
    db = request.app.state.db
    handoff = await get_cached(db, body.indexer_id, body.guid)
    if handoff is None:
        raise ApiError(
            404,
            "release is no longer cached; run the interactive search again "
            "before grabbing",
        )
    record = await request.app.state.commands.enqueue(
        "grab-release", handoff.model_dump(mode="json"), triggered_by="interactive"
    )
    return CommandResource.from_record(record)
