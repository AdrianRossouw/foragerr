"""The grab hand-off: the recorded intent to download an approved release.

Both automatic search (the search commands) and interactive search (the
``POST /release`` endpoint) converge here: instead of downloading, they enqueue
a persisted :class:`GrabReleaseCommand` carrying everything a downloader needs
(the release's indexer+guid identity, its NZB link, and the library series/issue
it satisfies). The command is the durable, trackable hand-off record.

Change 5 (m1-downloads, tracking area) makes the handler **live** (FRG-DL-006):
it resolves the protocol-matched download client, hands the release to it, and
records one ``grab_history`` row per issue keyed by the client download id — the
join key for all subsequent tracking, import, and failure handling. The command
name, payload contract, and every enqueue site are unchanged from the inert
change-4 seam, so nothing upstream had to move.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING, ClassVar, Iterable, Literal

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.search import Decision

if TYPE_CHECKING:  # avoid perturbing this pinned module's import graph
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("foragerr.search_ops.grab")


@register_command
class GrabReleaseCommand(BaseCommand):
    """Recorded intent to grab one approved release (FRG-SRCH-008/014).

    Runs on the ``download`` workload pool so change 5's real grab executes
    with download politeness. The payload is self-contained — a downloader
    needs no re-search to act on it. Inert until change 5.
    """

    name: Literal["grab-release"] = "grab-release"
    workload_class: ClassVar[str] = "download"

    #: Cross-indexer release identity + the cache key (FRG-IDX-007).
    indexer_id: int
    guid: str
    #: The NZB/download URL, fetched only via the ``external`` client profile.
    link: str
    title: str
    size_bytes: int | None = None
    #: The release's publish date (FRG-DL-006): persisted on ``grab_history`` and
    #: carried onto the blocklist so the usenet multi-field match (Sonarr SameNzb)
    #: can catch the SAME bad post resurfacing under a new guid (FRG-DL-012).
    #: Optional + additive, so no change-4 grab enqueue site had to move.
    pub_date: dt.datetime | None = None
    #: The library entities this release satisfies (resolved by the engine).
    series_id: int | None = None
    issue_id: int | None = None
    indexer_name: str | None = None


def handoff_from_decision(decision: Decision) -> GrabReleaseCommand:
    """Build the grab hand-off command from a decided release.

    The hand-off stamps the DECISION's own mapped identity — what the engine
    resolved this release actually IS (``mapped_series_id`` /
    ``mapped_issue_id``), NOT the issue a search happened to be launched for
    (FRG-SRCH-014). That keeps the ``(indexer_id, guid)`` cache key sound: two
    searches that surface the same release converge on one identity rather than
    overwriting each other with whichever issue was searched. An unmapped
    release carries ``issue_id=None`` (change 5 routes those to manual import).
    """
    candidate = decision.candidate
    return GrabReleaseCommand(
        indexer_id=candidate.indexer_id,
        guid=candidate.guid,
        link=candidate.link,
        title=candidate.title,
        size_bytes=candidate.size_bytes,
        pub_date=candidate.pub_date,
        series_id=decision.mapped_series_id,
        issue_id=decision.mapped_issue_id,
        indexer_name=candidate.indexer_name,
    )


async def enqueue_grab(ctx: HandlerContext, handoff: GrabReleaseCommand) -> int:
    """Enqueue the grab hand-off command and return its id (dedup-aware)."""
    record = await ctx.commands.enqueue(
        "grab-release", handoff.model_dump(), triggered_by="search"
    )
    return record.id


async def write_grab_history_rows(
    session: "AsyncSession",
    *,
    download_id: str,
    issues: Iterable[tuple[int | None, int | None]],
    indexer_id: int,
    indexer_name: str | None,
    guid: str,
    title: str,
    link: str,
    size_bytes: int | None,
    protocol: str,
    source: str,
    pub_date: dt.datetime | None = None,
    client_id: int | None = None,
    now: dt.datetime,
) -> int:
    """Write one ``grab_history`` row per issue, all sharing ``download_id``.

    ``download_id`` is the sole join key for tracking / import / failure handling
    (FRG-DL-006). A multi-issue release yields one row per issue sharing the id;
    every row carries the full release data so a tracked item's download_id can
    recover its originating grab. Returns the number of rows written.
    """
    from foragerr.downloads.models import GrabHistoryRow

    count = 0
    for series_id, issue_id in issues:
        session.add(
            GrabHistoryRow(
                download_id=download_id,
                client_id=client_id,
                series_id=series_id,
                issue_id=issue_id,
                indexer_id=indexer_id,
                indexer_name=indexer_name,
                guid=guid,
                title=title,
                link=link,
                size_bytes=size_bytes,
                pub_date=pub_date,
                protocol=protocol,
                source=source,
                created_at=now,
            )
        )
        count += 1
    return count


async def _enqueue_grab_followups(ctx: HandlerContext, protocol: str) -> None:
    """Event-trigger the post-grab commands (dedup-safe on the command backbone).

    Always refreshes tracking so the grab surfaces in the queue without waiting a
    scheduled interval. A DDL grab additionally triggers ``process-ddl-queue`` so
    the built-in downloader starts immediately (FRG-DDL-001/007) — usenet begins
    the moment ``client.download()`` uploads the NZB, but a DDL grab only enqueues
    a ``ddl_queue`` row and would otherwise idle until the scheduled drain.
    """
    from foragerr.downloads.registry import PROTOCOL_DDL

    if ctx.commands is None:
        return
    await ctx.commands.enqueue("track-downloads", {}, triggered_by="grab")
    if protocol == PROTOCOL_DDL:
        await ctx.commands.enqueue("process-ddl-queue", {}, triggered_by="grab")


@register_handler("grab-release")
async def _handle_grab_release(
    command: GrabReleaseCommand, ctx: HandlerContext
) -> str:
    """LIVE grab hand-off (FRG-DL-006): resolve the client, download, record.

    Resolves the enabled client matching the release's protocol (derived from
    ``indexer_id``), hands the release to ``client.download()``, then writes one
    ``grab_history`` row per issue keyed by the returned download id. A client
    that is unreachable at grab time (or the NZB fetch failing) raises a TYPED
    :class:`DownloadClientUnreachableError` / :class:`NoDownloadClientError` — a
    retryable command failure that leaves the release cache entry valid so the
    grab is never silently dropped. Bad release content raises the typed
    :class:`GrabValidationError`. The download id is the join key the tracking
    loop matches on.
    """
    # Lazily imported so this pinned module keeps its lean import graph and the
    # downloads.resolver -> search_ops.grab dependency never becomes a cycle.
    from sqlalchemy import select

    from foragerr.db import utcnow
    from foragerr.downloads import make_download_factory
    from foragerr.downloads.models import SOURCE_DDL, SOURCE_INDEXER, GrabHistoryRow
    from foragerr.downloads.registry import PROTOCOL_DDL
    from foragerr.downloads.resolver import protocol_for_grab, resolve_client_for
    from foragerr.providers.backoff import ProviderBackoff

    factory = make_download_factory(ctx.settings)
    backoff = ProviderBackoff(ctx.db)

    # Resolve the protocol ONCE and hand it to resolve_client_for (rather than
    # resolve_client_for_grab, which would re-derive it) — one indexer read, no
    # TOCTOU on the stamped source.
    protocol = await protocol_for_grab(ctx.db, command)

    # Idempotency guard (FRG-DL-002/006): the side-effecting client.download()
    # runs before the grab_history commit, so a crash + orphan re-run of this
    # `started` command could re-download the same release. If a grab_history row
    # already exists for this command's (indexer_id, guid) identity, the download
    # already happened — resume to the tracking hand-off without re-downloading.
    async with ctx.db.read_session() as session:
        prior_download_id = (
            await session.execute(
                select(GrabHistoryRow.download_id)
                .where(
                    GrabHistoryRow.indexer_id == command.indexer_id,
                    GrabHistoryRow.guid == command.guid,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    if prior_download_id is not None:
        logger.info(
            "grab already handed off; skipping re-download (orphan re-run?)",
            extra={
                "download_id": prior_download_id,
                "indexer_id": command.indexer_id,
                "guid": command.guid,
            },
        )
        await _enqueue_grab_followups(ctx, protocol)
        return (
            f"grab already handed off: indexer={command.indexer_id} "
            f"guid={command.guid} download_id={prior_download_id}"
        )

    client = await resolve_client_for(
        ctx.db,
        protocol,
        http_factory=factory,
        backoff=backoff,
        app_settings=ctx.settings,
    )
    download_id = await client.download(command)

    now = utcnow()
    source = SOURCE_DDL if protocol == PROTOCOL_DDL else SOURCE_INDEXER
    client_id = client.client_id
    async with ctx.db.write_session() as session:
        await write_grab_history_rows(
            session,
            download_id=download_id,
            issues=[(command.series_id, command.issue_id)],
            indexer_id=command.indexer_id,
            indexer_name=command.indexer_name,
            guid=command.guid,
            title=command.title,
            link=command.link,
            size_bytes=command.size_bytes,
            pub_date=command.pub_date,
            protocol=protocol,
            source=source,
            client_id=client_id,
            now=now,
        )

    # Event-trigger the follow-up refresh/drain so the grab surfaces (and a DDL
    # grab starts) without waiting a full scheduled interval.
    await _enqueue_grab_followups(ctx, protocol)

    logger.info(
        "grab handed to download client",
        extra={
            "download_id": download_id,
            "indexer_id": command.indexer_id,
            "guid": command.guid,
            "series_id": command.series_id,
            "issue_id": command.issue_id,
            "protocol": protocol,
        },
    )
    return (
        f"grab downloaded: indexer={command.indexer_id} guid={command.guid} "
        f"issue={command.issue_id} download_id={download_id}"
    )
