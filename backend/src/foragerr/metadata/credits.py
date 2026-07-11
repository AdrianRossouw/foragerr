"""ComicVine person-credit mapping + role normalization (FRG-CRTR-001).

Pure and I/O-free: turns an untrusted CV ``person_credits`` value into typed,
sanitized :class:`~foragerr.metadata.models.CreditRecord` entries, and
normalizes CV's free-ish role strings onto a fixed vocabulary.

This lives in :mod:`foragerr.metadata` (not the ``creators`` domain) so the
ingest mapper (:func:`foragerr.metadata.mapping.map_issue`) can call it without
crossing the metadata import boundary. The ``creators`` ORM CHECK constraint
imports :data:`ROLE_VOCABULARY` from here so the mapper and the live schema model
track one definition. The 0016 migration deliberately does NOT import it — it
freezes its own copy of the vocabulary (historical migrations are immutable); a
test asserts the two match today and fails the day they intentionally diverge.
"""

from __future__ import annotations

import logging
from typing import Any

from foragerr.metadata.models import CreditRecord
from foragerr.metadata.sanitize import sanitize_cv_text

logger = logging.getLogger("foragerr.metadata.credits")

#: The fixed normalized-role vocabulary (FRG-CRTR-001). Every persisted
#: ``role_normalized`` is exactly one of these; unknown/compound CV role parts
#: fall through to ``"other"`` with the verbatim token retained.
ROLE_VOCABULARY = (
    "writer",
    "artist",
    "penciler",
    "inker",
    "colorist",
    "letterer",
    "cover",
    "editor",
    "other",
)

#: Hard upper bound on credit records emitted for ONE issue, applied after dedup.
#: Real issues rarely carry more than ~30 credits; this cap stops a hostile or
#: pathologically-large CV ``person_credits`` payload from exploding into an
#: unbounded ``issue_credits`` insert inside a single refresh write transaction
#: (RISK-011 resource-exhaustion arm). The excess is dropped with one debug log.
MAX_CREDITS_PER_ISSUE = 100

#: Known CV role spellings -> a vocabulary slot. Keys are casefolded; anything
#: not here maps to ``"other"``. Deliberately includes the obvious CV variants
#: (``penciller``/``colourist``/``cover artist``/``editor in chief``) and the
#: writing-adjacent roles (``plotter``/``scripter``) so they don't all collapse
#: to ``other``. Extending this table is a data-only change (no migration).
_ROLE_ALIASES = {
    "writer": "writer",
    "plotter": "writer",
    "scripter": "writer",
    "artist": "artist",
    "penciler": "penciler",
    "penciller": "penciler",
    "inker": "inker",
    "colorist": "colorist",
    "colourist": "colorist",
    "letterer": "letterer",
    "cover": "cover",
    "cover artist": "cover",
    "editor": "editor",
    "editor in chief": "editor",
}


def normalize_role(token: str) -> str:
    """Map one already-split, sanitized role token onto :data:`ROLE_VOCABULARY`.

    Unknown tokens map to ``"other"`` (the verbatim token is retained by the
    caller). Matching is casefold/strip-insensitive.
    """
    return _ROLE_ALIASES.get(token.strip().casefold(), "other")


def map_person_credits(value: Any) -> tuple[CreditRecord, ...]:
    """Map an untrusted CV ``person_credits`` value to typed credit entries.

    Total by contract (FRG-CRTR-001 / FRG-META-006): an absent, empty, or
    malformed value maps to ``()`` and never raises. Individual entries missing
    a usable person id or whose name sanitizes to nothing are dropped (logged at
    debug). A compound CV role (``"penciler, inker"``) is split into one entry
    per ``(person, normalized role)``; duplicates within the issue collapse.
    """
    if not isinstance(value, list):
        if value not in (None, ()):
            logger.debug("dropping malformed person_credits value: %r", value)
        return ()
    out: list[CreditRecord] = []
    seen: set[tuple[int, str]] = set()
    for raw in value:
        if not isinstance(raw, dict):
            logger.debug("dropping non-object person_credits entry: %r", raw)
            continue
        person_id = _person_id(raw.get("id"))
        if person_id is None:
            logger.debug("dropping person_credit with missing/invalid id: %r", raw)
            continue
        name = sanitize_cv_text(_stringish(raw.get("name")))
        if not name:
            logger.debug("dropping person_credit %d with empty name", person_id)
            continue
        for verbatim, normalized in _split_roles(raw.get("role")):
            key = (person_id, normalized)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                CreditRecord(
                    cv_person_id=person_id,
                    name=name,
                    role_verbatim=verbatim,
                    role_normalized=normalized,
                )
            )
    if len(out) > MAX_CREDITS_PER_ISSUE:
        # Bound the per-issue row count (RISK-011): truncate an oversized payload
        # rather than let it drive an unbounded insert.
        logger.debug(
            "person_credits: capping %d credits to the %d-per-issue maximum",
            len(out),
            MAX_CREDITS_PER_ISSUE,
        )
        out = out[:MAX_CREDITS_PER_ISSUE]
    return tuple(out)


def _split_roles(value: Any) -> list[tuple[str, str]]:
    """Sanitize + comma-split a CV role string into (verbatim, normalized) pairs.

    An absent/empty role yields a single ``("", "other")`` pair so a credited
    person is never dropped merely for lacking a role.
    """
    cleaned = sanitize_cv_text(_stringish(value)) if value is not None else None
    if not cleaned:
        return [("", "other")]
    pairs: list[tuple[str, str]] = []
    for part in cleaned.split(","):
        token = part.strip()
        if not token:
            continue
        pairs.append((token, normalize_role(token)))
    return pairs or [("", "other")]


def _person_id(value: Any) -> int | None:
    """A positive CV person id from an int or numeric string, else ``None``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _stringish(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)
