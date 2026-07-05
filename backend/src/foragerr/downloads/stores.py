"""Live queue + blocklist stores backing the change-4 dynamic-store seams.

Change 4 shipped the ``AlreadyQueuedSpec`` and ``BlocklistSpec`` with fully
written reject paths but inert defaults
(:class:`~foragerr.search.context.EmptyQueue` / ``EmptyBlocklist``): every
candidate was accepted because nothing was ever queued or blocklisted. This
module supplies the real stores (FRG-DL-012/013) — swapped into the
:class:`~foragerr.search.EvaluationContext` where the search pipeline builds it
(``search_ops.context.build_evaluation_context``) — so those specifications
evaluate live without a single edit to a spec.

Both stores are immutable in-memory SNAPSHOTS loaded once per search from the
same read session as the library snapshot: the decision engine is pure and
synchronous, so the stores expose only synchronous ``is_queued`` /
``is_blocklisted`` lookups over pre-loaded rows (mirroring how the library view
is resolved async then queried sync).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.downloads.models import SOURCE_DDL, BlocklistRow, TrackedDownloadRow
from foragerr.downloads.registry import PROTOCOL_DDL
from foragerr.downloads.state import TrackedDownloadState
from foragerr.releases import ReleaseCandidate

#: Tracked-download states that count as "actively queued" for the already-queued
#: specification (FRG-DL-013): while a download for an issue is in flight or
#: awaiting import, a fresh grab of the SAME issue is suppressed. ``failed`` and
#: ``ignored`` are deliberately EXCLUDED so the failure loop's auto re-search can
#: proceed and grab an alternative release.
ACTIVE_QUEUE_STATES = frozenset(
    {
        TrackedDownloadState.DOWNLOADING,
        TrackedDownloadState.IMPORT_BLOCKED,
        TrackedDownloadState.IMPORT_PENDING,
        TrackedDownloadState.FAILED_PENDING,
        TrackedDownloadState.IMPORTING,
        TrackedDownloadState.IMPORTED,
    }
)


class QueueStore:
    """Live :class:`~foragerr.search.QueueLookup` over ``tracked_downloads``.

    Holds the set of ``(series_id, issue_id)`` pairs with an actively-queued
    tracked download (FRG-DL-013). A snapshot: safe to share across one search.
    """

    __slots__ = ("_queued",)

    def __init__(self, queued: frozenset[tuple[int, int]]) -> None:
        self._queued = queued

    def is_queued(self, series_id: int, issue_id: int) -> bool:
        return (series_id, issue_id) in self._queued


@dataclass(frozen=True, slots=True)
class BlocklistEntry:
    """One blocklisted release's multi-field match key (FRG-DL-012)."""

    guid: str | None
    indexer_id: int | None
    indexer_name: str | None
    title: str | None
    size_bytes: int | None
    publish_date: datetime | None
    protocol: str | None
    source: str | None
    source_url: str | None

    def matches(self, candidate: ReleaseCandidate) -> bool:
        """Whether ``candidate`` is this blocklisted release resurfacing.

        - **Exact identity**: the same ``(indexer_id, guid)`` — a re-grab of the
          literal cached release.
        - **DDL** (``source``/``protocol`` = ``ddl``): the same source URL or
          title, since a GetComics post has no stable guid.
        - **Usenet**: the same title + indexer + size, so the same bad post is
          caught even when it resurfaces under a NEW guid (Sonarr's ``SameNzb``
          match, the reason a multi-field key beats Mylar's id-only). Publish
          date is a TIE-CHECKER, not a mandatory key: it may only VETO a match
          when it is present on BOTH sides and differs — a missing pub_date on
          either side never vetoes an otherwise-strong title+indexer+size match.
        """
        if (
            self.guid is not None
            and self.guid == candidate.guid
            and (self.indexer_id is None or self.indexer_id == candidate.indexer_id)
        ):
            return True
        # A DDL entry matches by source URL/title, not guid+indexer. Compare the
        # PROTOCOL against PROTOCOL_DDL and the SOURCE against SOURCE_DDL — they
        # both equal "ddl" but belong to different namespaces (protocol vs source).
        if self.protocol == PROTOCOL_DDL or self.source == SOURCE_DDL:
            if self.source_url is not None and self.source_url == candidate.link:
                return True
            if self.title is not None and self.title == candidate.title:
                return True
            return False
        return (
            self.title is not None
            and self.title == candidate.title
            and self.indexer_name is not None
            and self.indexer_name == candidate.indexer_name
            and self.size_bytes is not None
            and self.size_bytes == candidate.size_bytes
            and (
                self.publish_date is None
                or candidate.pub_date is None
                or self.publish_date == candidate.pub_date
            )
        )


class BlocklistStore:
    """Live :class:`~foragerr.search.BlocklistLookup` over the blocklist table.

    A snapshot of every blocklist entry; a candidate is rejected if ANY entry
    matches it (FRG-DL-012). Deleting a blocklist row (and rebuilding the store on
    the next search) re-enables grabbing that release.
    """

    __slots__ = ("_entries",)

    def __init__(self, entries: tuple[BlocklistEntry, ...]) -> None:
        self._entries = entries

    def is_blocklisted(self, candidate: ReleaseCandidate) -> bool:
        return any(entry.matches(candidate) for entry in self._entries)


async def load_queue_store(session: AsyncSession) -> QueueStore:
    """Snapshot the actively-queued ``(series_id, issue_id)`` pairs (FRG-DL-013)."""
    rows = (
        await session.execute(
            select(
                TrackedDownloadRow.series_id,
                TrackedDownloadRow.issue_id,
                TrackedDownloadRow.state,
            )
        )
    ).all()
    queued = frozenset(
        (series_id, issue_id)
        for series_id, issue_id, state in rows
        if series_id is not None
        and issue_id is not None
        and state in ACTIVE_QUEUE_STATES
    )
    return QueueStore(queued)


async def load_blocklist_store(session: AsyncSession) -> BlocklistStore:
    """Snapshot the blocklist table into a live match store (FRG-DL-012)."""
    rows = (await session.execute(select(BlocklistRow))).scalars().all()
    entries = tuple(
        BlocklistEntry(
            guid=row.guid,
            indexer_id=row.indexer_id,
            indexer_name=row.indexer_name,
            title=row.source_title,
            size_bytes=row.size_bytes,
            publish_date=row.publish_date,
            protocol=row.protocol,
            source=row.source,
            source_url=row.source_url,
        )
        for row in rows
    )
    return BlocklistStore(entries)


__all__ = [
    "ACTIVE_QUEUE_STATES",
    "BlocklistEntry",
    "BlocklistStore",
    "QueueStore",
    "load_blocklist_store",
    "load_queue_store",
]
