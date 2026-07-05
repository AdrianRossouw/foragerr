"""The ``series-search`` command handler (FRG-SER-005, FRG-SRCH-008).

The add flow enqueues ``series-search`` for a series' missing monitored issues.
The handler is registered here — the single registration site the app already
imports via ``foragerr.library.flows`` — but the live search body lives in the
integration area ``foragerr.search_ops`` (change 4). It is imported lazily
inside the handler so the library-flows package carries no import-time
dependency on ``search_ops`` (which itself reads library flows), keeping the two
packages free of an import cycle.
"""

from __future__ import annotations

from foragerr.commands.registry import register_handler
from foragerr.commands.service import HandlerContext

from foragerr.library.flows._common import SeriesSearchCommand


@register_handler("series-search")
async def _handle_series_search(
    command: SeriesSearchCommand, ctx: HandlerContext
) -> str:
    # Lazy import: search_ops depends on library.flows, so importing it at
    # module load would form a cycle. Deferring to call time breaks it.
    from foragerr.search_ops.commands import run_series_search

    return await run_series_search(command, ctx)
