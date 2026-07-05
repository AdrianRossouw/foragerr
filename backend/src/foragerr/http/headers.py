"""Shared parsing for standard outbound-response headers.

One home for header parsing every outbound integration needs, so the indexer
client and the ComicVine client cannot drift in how they read (e.g.) a
rate-limit ``Retry-After`` (FRG-NFR-006).
"""

from __future__ import annotations

from typing import Mapping


def parse_retry_after(headers: Mapping[str, str]) -> float | None:
    """The ``Retry-After`` delay in seconds, or ``None``.

    Only the numeric-seconds form is honored; the HTTP-date form is ignored
    (treated as absent) — both the indexer and ComicVine back-off ladders take
    ``None`` to mean "use the default back-off", so an un-parseable value is
    safe to drop.
    """
    raw = headers.get("retry-after")
    if raw is None:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return float(raw)
    return None
