"""Inert ``series-search`` handler (FRG-SER-005).

The add flow can enqueue a search for missing monitored issues, but the
actual indexer/DDL search lands in change 4 (m1-search-indexers). Registering
the command + a recognised, inert handler now means the enqueue/dedup/priority
and job-history semantics are already real and observable through the command
API — only the search body is deferred.
"""

from __future__ import annotations

from foragerr.commands.registry import register_handler
from foragerr.commands.service import HandlerContext

from foragerr.library.flows._common import SeriesSearchCommand


@register_handler("series-search")
async def _handle_series_search(
    command: SeriesSearchCommand, ctx: HandlerContext
) -> str:
    return "search deferred to change 4 (m1-search-indexers)"
