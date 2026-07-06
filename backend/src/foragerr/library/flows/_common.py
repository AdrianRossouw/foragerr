"""Shared plumbing for the library business-logic flows (change 3).

Typed flow-level exceptions, the ``SeriesRefreshed`` domain event, the add-
option JSON codec, the add-time monitoring-strategy vocabulary, small value
helpers, and the three chained command models (``refresh-series`` ->
``scan-series`` -> optional ``series-search``).

These flows sit on TOP of two frozen sibling packages — ``foragerr.library``
(domain + repo + paths + ordering) and ``foragerr.metadata`` (the typed
ComicVine client) — and never modify either. Everything here raises plain,
module-local exceptions (never :class:`foragerr.api.errors.ApiError`); the
future API layer translates them into HTTP responses.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal

from foragerr.commands.registry import BaseCommand, register_command
from foragerr.config import Settings
from foragerr.http import HttpClientFactory
from foragerr.library.models import MONITOR_NEW_ITEMS_POLICIES

logger = logging.getLogger("foragerr.library.flows")

# --- exceptions -------------------------------------------------------------


class SeriesValidationError(ValueError):
    """A series add/edit request failed validation (maps to HTTP 400).

    Raised BEFORE any row/command/path is created or mutated, so a rejected
    request leaves no partial state behind (FRG-SER-005/008).
    """


class SeriesNotFoundError(LookupError):
    """No series exists for the given id (maps to HTTP 404)."""


class DeleteFilesNotSupportedError(NotImplementedError):
    """``deleteFiles=true`` is deliberately unimplemented in M1 (HTTP 501).

    Raised before any row is deleted or file touched (FRG-SER-014).
    """


# --- domain event -----------------------------------------------------------


@dataclass(frozen=True)
class SeriesRefreshed:
    """Emitted after a series metadata refresh commits (FRG-META-008).

    ``partial`` is ``True`` when the ComicVine issue fetch was incomplete, so
    the delete arm of reconciliation was skipped.
    """

    series_id: int
    partial: bool


# --- add-time monitoring strategies (FRG-SER-006) ---------------------------

#: The six add-time monitoring strategies, applied ONCE over the issues the
#: first refresh persists, then cleared. Distinct from the series-level
#: ``monitor_new_items`` policy (FRG-SER-007) that governs LATER refreshes.
MONITOR_STRATEGIES = ("all", "none", "future", "missing", "existing", "first")


# --- add-option codec -------------------------------------------------------


def encode_add_options(
    *, monitor_strategy: str, monitor_new_items: str, search_on_add: bool
) -> str:
    """Canonical-JSON encoding of the add options stored on ``series.add_options``."""
    return json.dumps(
        {
            "monitor_strategy": monitor_strategy,
            "monitor_new_items": monitor_new_items,
            "search_on_add": bool(search_on_add),
        },
        sort_keys=True,
    )


# --- alias codec (FRG-SRCH-003) ---------------------------------------------

#: Cap on the number of user aliases stored per series — a small, sane bound so
#: the JSON column can never grow unbounded from a bad edit.
MAX_SERIES_ALIASES = 50

#: Cap on the length of a single alias — a matching key is short; a multi-KB
#: "alias" is a bad edit, not a search name, so it is rejected before storage.
MAX_ALIAS_LENGTH = 200


def encode_aliases(aliases: list[str] | tuple[str, ...] | None) -> str | None:
    """Canonical-JSON encoding of user aliases for ``series.aliases``.

    Strips whitespace, drops blank entries, and de-duplicates while preserving
    first-seen order. Returns ``None`` (SQL NULL) for an empty result so an
    aliasless series stores nothing rather than an empty array.
    """
    if not aliases:
        return None
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in aliases:
        text = (raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    if not cleaned:
        return None
    return json.dumps(cleaned, ensure_ascii=False)


def decode_aliases(
    raw: str | None, *, series_id: int | None = None
) -> tuple[str, ...]:
    """Decode ``series.aliases`` into the raw user strings (empty when unset).

    A corrupt ``aliases`` value (invalid JSON) degrades to ``()`` — the same
    path a non-list value already takes — with a warning, so one bad row can
    never wedge the series list or a search that reads aliases (FRG-SRCH-003).
    """
    if not raw:
        return ()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "malformed series aliases JSON; treating as no aliases",
            extra={"series_id": series_id},
        )
        return ()
    if not isinstance(data, list):
        return ()
    return tuple(str(item) for item in data)


def validate_aliases(aliases: list[str]) -> None:
    """Reject an alias edit that exceeds the stored caps (FRG-SRCH-003).

    Two bounds: the number of aliases, and the length of any single alias — a
    matching key is short, so a multi-KB entry is a bad edit, not a name.
    """
    if len(aliases) > MAX_SERIES_ALIASES:
        raise SeriesValidationError(
            f"too many aliases ({len(aliases)}); at most "
            f"{MAX_SERIES_ALIASES} alternate search names are allowed"
        )
    for alias in aliases:
        if len(alias) > MAX_ALIAS_LENGTH:
            raise SeriesValidationError(
                f"alias too long ({len(alias)} chars); at most "
                f"{MAX_ALIAS_LENGTH} characters are allowed per alias"
            )


@dataclass(frozen=True)
class AddOptions:
    """Decoded ``series.add_options`` payload."""

    monitor_strategy: str
    monitor_new_items: str
    search_on_add: bool


def decode_add_options(raw: str | None) -> AddOptions | None:
    """Decode ``series.add_options``; ``None`` when unset (already applied)."""
    if not raw:
        return None
    data = json.loads(raw)
    return AddOptions(
        monitor_strategy=data.get("monitor_strategy", "all"),
        monitor_new_items=data.get("monitor_new_items", "all"),
        search_on_add=bool(data.get("search_on_add", False)),
    )


# --- value helpers ----------------------------------------------------------


def iso_to_date(value: str | None) -> dt.date | None:
    """Parse a ComicVine ISO date string to a ``date`` (guarding ``None``).

    ComicVine dates arrive as strings (``IssueRecord.cover_date`` /
    ``store_date``); the library columns are typed ``date``. A malformed or
    partial value (e.g. a ``"2020-05-00"`` day-zero date) degrades to
    ``None`` rather than raising.
    """
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def monitored_for_new_items(policy: str) -> bool:
    """Map a ``monitor_new_items`` policy to the ``monitored`` flag a refresh-
    discovered issue is created with (FRG-SER-007)."""
    return policy == "all"


def validate_monitor_new_items(policy: str) -> None:
    if policy not in MONITOR_NEW_ITEMS_POLICIES:
        raise SeriesValidationError(
            f"invalid monitor_new_items {policy!r}; "
            f"expected one of {list(MONITOR_NEW_ITEMS_POLICIES)}"
        )


def validate_monitor_strategy(strategy: str) -> None:
    if strategy not in MONITOR_STRATEGIES:
        raise SeriesValidationError(
            f"invalid monitor strategy {strategy!r}; "
            f"expected one of {list(MONITOR_STRATEGIES)}"
        )


# --- ComicVine factory hook -------------------------------------------------


def comicvine_factory(settings: Settings) -> HttpClientFactory:
    """Build the outbound HTTP factory for a ComicVine call site.

    A fresh factory per call is cheap and correct: the process-global CV rate
    limiter lives in :mod:`foragerr.metadata.ratelimit`, so serialization
    holds across factory instances. This single indirection is the seam tests
    monkeypatch to route the real :class:`~foragerr.metadata.ComicVineClient`
    at an injected transport instead of the live network.
    """
    return HttpClientFactory(settings)


# --- chained command models (FRG-SER-005) -----------------------------------


def cover_paths(settings: Settings, series_id: int) -> tuple[Path, Path]:
    """The cached-cover JPEG and its URL-tracking sidecar for one series.

    Shared by the refresh cover-cache (which writes them) and series delete
    (which must remove them) so the naming scheme lives in exactly one place.
    """
    covers_dir = Path(settings.config_dir) / "covers"
    return covers_dir / f"{series_id}.jpg", covers_dir / f"{series_id}.url"


@register_command
class RefreshSeriesCommand(BaseCommand):
    """Re-fetch a series' ComicVine metadata + issues and reconcile
    (FRG-META-008). Enqueued by the add flow and, later, by schedule/manual."""

    name: Literal["refresh-series"] = "refresh-series"
    series_id: int


@register_command
class ScanSeriesCommand(BaseCommand):
    """Scan a series' on-disk folder and match files to issues (FRG-SER-005)."""

    name: Literal["scan-series"] = "scan-series"
    series_id: int


@register_command
class SeriesSearchCommand(BaseCommand):
    """Search every wanted issue of one series (FRG-SER-005 / FRG-SRCH-008).

    Runs on the ``search`` workload pool. The handler (registered in
    :mod:`foragerr.search_ops.commands`, change 4) fans each wanted issue
    through the shared search pipeline and records a grab hand-off for the best
    approved release per issue; the ``search`` pool size of 1 serializes indexer
    politeness across the walk."""

    name: Literal["series-search"] = "series-search"
    workload_class: ClassVar[str] = "search"
    series_id: int
