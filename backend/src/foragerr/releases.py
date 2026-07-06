"""The release-candidate contract shared by indexers and search (FRG-IDX-007).

``ReleaseCandidate`` is the normalized record every indexer response item is
mapped into (FRG-IDX-007) and the sole input type the decision engine evaluates
(FRG-SRCH-001). It sits in its own module because two independent worktree
areas depend on it — indexer parsing produces candidates, the engine consumes
them — and neither owns the other's package.

Same rules as :mod:`foragerr.metadata.models`: typed and sentinel-free, no
persistence concerns. Title text is preserved verbatim (release titles are the
parser's input under the FRG-SRCH-002 contract — they are untrusted and must
round-trip unmodified into rejection reasons and history records, where output
encoding is the renderer's job).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    """One normalized release from one indexer (FRG-IDX-007).

    ``guid`` is unique only per indexer — cross-indexer identity is
    (``indexer_id``, ``guid``), the grab-cache key (FRG-SRCH-014).
    """

    guid: str
    title: str
    #: Download (NZB) URL — fetched only via the ``external`` client profile.
    link: str
    indexer_id: int
    indexer_name: str
    #: Indexer priority copied from the row at parse time, for the comparator
    #: (FRG-SRCH-007) and cross-indexer dedup (FRG-SRCH-010).
    indexer_priority: int
    #: Query-ladder tier that produced this result, 0 = most specific
    #: (FRG-IDX-005); comparator prefers lower tiers.
    query_tier: int
    size_bytes: int | None
    pub_date: datetime | None
    categories: tuple[int, ...] = ()
    #: Passthrough of ``newznab:attr`` name/value pairs not lifted into typed
    #: fields; values are raw strings.
    attributes: dict[str, str] = field(default_factory=dict)
