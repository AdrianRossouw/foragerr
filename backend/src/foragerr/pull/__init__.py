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

Out of scope here (later areas of this same change build on top of this
package): the external fetch client (``pull/source.py``, area B), the
matching engine (``pull/matching.py``, area C), the refresh-trigger +
scheduled/manual command (``pull/commands.py``, area D), and the projection +
read endpoint (``pull/projection.py`` / ``api/pull.py``, area E).
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

__all__ = [
    "PULL_MATCH_TYPES",
    "UNMATCHED",
    "ParsedPullEntry",
    "PullEntryRow",
    "entry_key",
    "get_entry",
    "list_week",
    "replace_week",
    "update_match",
]
