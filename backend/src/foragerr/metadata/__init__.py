"""ComicVine metadata integration (FRG-META-001..008, 013, 014).

The single module boundary through which foragerr talks to ComicVine: a typed
async client on the shared outbound factory, a process-global rate limiter
shared by every call site (covers included), offset pagination with a partial-
failure ``complete`` flag, pure JSON->record mapping, untrusted-content
sanitization, series search with plausibility annotations, and cover caching.

Depends only on ``foragerr.http``, ``foragerr.config``, ``foragerr.logging``,
``foragerr.parser.normalize`` (and ``foragerr.db.migrations.app_version`` for
the honest User-Agent) — never on the library/flows/api domains.
"""

from foragerr.metadata.comicvine import (
    DEFAULT_BASE,
    ComicVineClient,
    user_agent,
)
from foragerr.metadata.covers import cache_cover
from foragerr.metadata.errors import (
    COMICVINE_CREDENTIAL_MESSAGE,
    ComicVineAuthError,
    ComicVineError,
    ComicVineMalformedResponse,
    ComicVineRateLimited,
    ComicVineUnavailable,
    CoverHostNotAllowed,
)
from foragerr.metadata.mapping import map_issue, map_volume
from foragerr.metadata.models import (
    IssueRecord,
    IssueRef,
    Page,
    Plausibility,
    SearchResult,
    SeriesCandidate,
    SeriesRecord,
    SuggestResult,
)
from foragerr.metadata.ratelimit import (
    comicvine_degraded,
    comicvine_health,
    effective_interval,
)
from foragerr.metadata.sanitize import MAX_TEXT_LENGTH, sanitize_cv_text
from foragerr.metadata.search import plausibility

__all__ = [
    "COMICVINE_CREDENTIAL_MESSAGE",
    "DEFAULT_BASE",
    "MAX_TEXT_LENGTH",
    "ComicVineAuthError",
    "ComicVineClient",
    "ComicVineError",
    "ComicVineMalformedResponse",
    "ComicVineRateLimited",
    "ComicVineUnavailable",
    "CoverHostNotAllowed",
    "IssueRecord",
    "IssueRef",
    "Page",
    "Plausibility",
    "SearchResult",
    "SeriesCandidate",
    "SeriesRecord",
    "SuggestResult",
    "cache_cover",
    "comicvine_degraded",
    "comicvine_health",
    "effective_interval",
    "map_issue",
    "map_volume",
    "plausibility",
    "sanitize_cv_text",
    "user_agent",
]
