"""The grab hand-off: the recorded intent to download an approved release.

Both automatic search (the search commands) and interactive search (the
``POST /release`` endpoint) converge here: instead of downloading, they enqueue
a persisted :class:`GrabReleaseCommand` carrying everything a downloader needs
(the release's indexer+guid identity, its NZB link, and the library series/issue
it satisfies). The command is the durable, trackable hand-off record.

The handler is deliberately **inert** in this change (FRG-SRCH-008): it records
the intent and returns, performing no download. Change 5 (download clients + DDL)
replaces only the handler body — the command name, payload contract, and every
enqueue site stay exactly as they are here, so the grab hand-off is the stable
seam change 5 consumes.
"""

from __future__ import annotations

import logging
from typing import ClassVar, Literal

from pydantic import BaseModel

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.search import Decision

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
    #: The library entities this release satisfies (resolved by the engine).
    series_id: int | None = None
    issue_id: int | None = None
    indexer_name: str | None = None


class GrabHandoff(BaseModel):
    """The grab payload derived from a decided release (test/typed view)."""

    indexer_id: int
    guid: str
    link: str
    title: str
    size_bytes: int | None = None
    series_id: int | None = None
    issue_id: int | None = None
    indexer_name: str | None = None

    def payload(self) -> dict:
        """The enqueue payload for :class:`GrabReleaseCommand`."""
        return self.model_dump()


def handoff_from_decision(
    decision: Decision, *, issue_id: int | None = None
) -> GrabHandoff:
    """Build the grab hand-off payload from an approved decision.

    ``issue_id`` (the searched issue) overrides the mapped issue when supplied,
    so an automatic single-issue search records the issue it was launched for
    even if the engine mapped the release to the same issue independently.
    """
    candidate = decision.candidate
    return GrabHandoff(
        indexer_id=candidate.indexer_id,
        guid=candidate.guid,
        link=candidate.link,
        title=candidate.title,
        size_bytes=candidate.size_bytes,
        series_id=decision.mapped_series_id,
        issue_id=issue_id if issue_id is not None else decision.mapped_issue_id,
        indexer_name=candidate.indexer_name,
    )


async def enqueue_grab(ctx: HandlerContext, handoff: GrabHandoff) -> int:
    """Enqueue the grab hand-off command and return its id (dedup-aware)."""
    record = await ctx.commands.enqueue(
        "grab-release", handoff.payload(), triggered_by="search"
    )
    return record.id


@register_handler("grab-release")
async def _handle_grab_release(
    command: GrabReleaseCommand, ctx: HandlerContext
) -> str:
    """INERT grab hand-off (FRG-SRCH-008). Records intent; downloads nothing.

    Change 5 replaces this body with the real download-client / DDL hand-off;
    the command contract and enqueue sites are unchanged."""
    logger.info(
        "grab hand-off recorded (inert until change 5)",
        extra={
            "indexer_id": command.indexer_id,
            "guid": command.guid,
            "series_id": command.series_id,
            "issue_id": command.issue_id,
        },
    )
    return (
        f"grab recorded (inert): indexer={command.indexer_id} "
        f"guid={command.guid} issue={command.issue_id}"
    )
