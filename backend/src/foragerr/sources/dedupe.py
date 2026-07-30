"""md5-identical entitlement linking (FRG-SRC-015).

A store sells the same file in several bundles. Each purchase is its own
entitlement — a distinct store-native key, so the sync diff is right to keep
both — but they carry the SAME store-computed md5, which means accepting both
downloads the same bytes twice and the second import is blocked as a duplicate
with nothing to explain it. Linking collapses such a set to ONE reviewable unit:
the earliest row stays canonical and every other member parks at
``review_status = "duplicate"`` with :attr:`SourceEntitlementRow.duplicate_of`
pointing at it.

**One rule, applied in two places.** A set links only while EVERY member of it
is still ``new``:

* a decided row (``matched`` / ``ignored``) is the operator's, and re-shaping
  the set around it would either park a row behind a withdrawal or hide a row
  whose twin was already imported under a decision the operator never made about
  THIS row;
* an already-parked copy makes the set non-``new``, which is what makes both
  entry points idempotent by construction — a second pass finds the set no
  longer all-``new`` and does nothing.

The consequence is the one the spec names: once any member is decided the set
freezes, so restoring a copy while its twin stays decided leaves it independently
reviewable, while restoring it back alongside an still-``new`` twin lets the next
pass re-link the pair.

Rows with no stored md5 are never linked — absence of the signal is not evidence
of identity. Linking is same-source by construction (the scan is source-scoped):
two stores selling the same bytes are two purchases with two provenances, and
cross-source dedupe is an explicit non-goal.

The startup hook exists because the operator's existing review queue must
collapse at upgrade, not at whatever future moment the next sync happens to run.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import select

from foragerr.db.base import utcnow
from foragerr.sources.models import SourceEntitlementRow

logger = logging.getLogger("foragerr.sources.dedupe")

__all__ = [
    "duplicate_backfill_startup_hook",
    "link_duplicate_entitlements",
]


async def link_duplicate_entitlements(db, source_id: int | None = None) -> int:
    """Park every non-canonical member of an all-``new`` same-md5 set.

    ``source_id`` bounds the scan to one source (the sync path); ``None`` scans
    every source (the startup backfill). Returns the number of rows parked.

    Runs as ONE write transaction so a set moves together — a half-linked set
    would show the operator a copies chip whose members are still counted as
    pending. The read that decides which sets qualify happens inside it, so a
    concurrent match/ignore either lands before the decision (and disqualifies
    the set) or after the parking (and is a decision on a canonical row, which
    the set is allowed to carry).
    """
    parked = 0
    async with db.write_session() as session:
        stmt = select(SourceEntitlementRow).where(
            SourceEntitlementRow.md5.is_not(None)
        )
        if source_id is not None:
            stmt = stmt.where(SourceEntitlementRow.source_id == source_id)
        rows = (await session.execute(stmt.order_by(SourceEntitlementRow.id))).scalars()
        sets: dict[tuple[int, str], list[SourceEntitlementRow]] = defaultdict(list)
        for row in rows:
            if not row.md5:
                continue  # an empty string is no more a fingerprint than NULL
            sets[(row.source_id, row.md5)].append(row)
        now = utcnow()
        for members in sets.values():
            if len(members) < 2:
                continue
            if any(member.review_status != "new" for member in members):
                continue
            canonical, *copies = members  # id-ordered: the earliest is canonical
            for copy in copies:
                copy.review_status = "duplicate"
                copy.duplicate_of = canonical.id
                copy.updated_at = now
                parked += 1
    if parked:
        logger.info(
            "sources.dedupe: parked %d byte-identical entitlement copy(ies)",
            parked,
        )
    return parked


async def duplicate_backfill_startup_hook(app) -> None:
    """Link pre-existing all-``new`` md5 sets once, at boot (FRG-SRC-015).

    Idempotent by construction (a linked set is no longer all-``new``), so it
    needs no completion marker. Never fatal: a failure is logged and the boot
    continues with the rows unlinked, and the next start retries.
    """
    db = getattr(app.state, "db", None)
    if db is None:  # pragma: no cover — the db area always runs first
        return
    try:
        await link_duplicate_entitlements(db)
    except Exception:  # noqa: BLE001 — a stalled backfill must not block boot
        logger.exception(
            "sources.dedupe: duplicate backfill failed; entitlements are "
            "unchanged and the next start will retry"
        )
