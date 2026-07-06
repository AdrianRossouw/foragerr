"""The pull domain: the weekly-release backbone (FRG-PULL-001..006).

Public surface (area A — storage; see ``openspec/changes/m3-pull-backbone``):

- :mod:`foragerr.pull.models` — :class:`PullEntryRow` (the persisted
  ``pull_entries`` row, FRG-PULL-003) and :class:`ParsedPullEntry` (the
  DB-free typed shape the fetch client, area B, parses untrusted source JSON
  into), plus :func:`entry_key` (the deterministic per-week identity).
- :mod:`foragerr.pull.repo` — :func:`replace_week` (the per-week idempotent
  replace-on-refresh store), :func:`list_week`, :func:`get_entry`, and
  :func:`update_match` (the matcher's, area C, write path onto an
  already-stored entry).
- :mod:`foragerr.pull.source` (area B) — :class:`PullSourceClient` (the
  hardened external fetch, FRG-PULL-002) yielding a :class:`PullFetchOutcome`
  of :class:`ParsedPullEntry` per week; area D drives storage from it.

Out of scope here (later areas of this same change build on top of this
package): the matching engine (``pull/matching.py``, area C), the
refresh-trigger + scheduled/manual command (``pull/commands.py``, area D), and
the projection + read endpoint (``pull/projection.py`` / ``api/pull.py``,
area E).
"""

from __future__ import annotations

from foragerr.pull.models import (
    PULL_MATCH_TYPES,
    UNMATCHED,
    ParsedPullEntry,
    PullEntryRow,
    entry_key,
)
from foragerr.pull.repo import get_entry, list_week, replace_week, update_match
from foragerr.pull.source import (
    PullBadDate,
    PullFetchOutcome,
    PullSourceClient,
    PullSourceError,
    PullSourceOutage,
    PullWeekResult,
    parse_pull_payload,
)

__all__ = [
    "PULL_MATCH_TYPES",
    "UNMATCHED",
    "ParsedPullEntry",
    "PullBadDate",
    "PullEntryRow",
    "PullFetchOutcome",
    "PullSourceClient",
    "PullSourceError",
    "PullSourceOutage",
    "PullWeekResult",
    "entry_key",
    "get_entry",
    "list_week",
    "parse_pull_payload",
    "replace_week",
    "update_match",
]
