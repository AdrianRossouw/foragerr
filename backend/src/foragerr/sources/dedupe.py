"""md5-identical entitlement linking (FRG-SRC-015).

A store sells the same file in several bundles. Each purchase is its own
entitlement — a distinct store-native key, so the sync diff is right to keep
both — but they carry the SAME store-computed md5, which means accepting both
downloads the same bytes twice and the second import is blocked as a duplicate
with nothing to explain it. Linking collapses such a set to ONE reviewable unit:
the canonical row stays reviewable and every other member parks at
``review_status = "duplicate"`` with :attr:`SourceEntitlementRow.duplicate_of`
pointing at it.

**What freezes a set.** A ``matched`` or ``ignored`` member is the operator's
decision, and re-shaping the set around it would either park a row behind a
withdrawal or hide a row whose twin was already imported under a decision the
operator never made about THIS row — so such a set links nothing further. An
already-parked member does NOT freeze it: a third bundle selling the same file
must still collapse onto the row the operator is already looking at, and a rule
that treated the parked copy as disqualifying left every later arrival to be
reviewed and downloaded on its own.

**Canonical** is the lowest-id member that is not itself parked. Parking is
therefore flat by construction — a third copy points at the same row the second
one does, never at the second copy — so the copies chip on one row discloses the
whole set and no pointer chain has to be walked to find it.

**Nothing the operator did is silently undone.** A copy the operator restored
carries :attr:`SourceEntitlementRow.dedupe_opt_out` and is never parked again;
it can still BE a canonical, because it is an ordinary reviewable row.
Idempotence comes from that flag plus the fact that a parked row is not
re-parked — not from the set's overall state.

**Unparking.** Store-side bytes change: a re-upload rewrites an md5, a payload
that omits the digest nulls one. A copy whose md5 no longer equals its
canonical's — or whose pointer names no row — has lost the evidence it was
parked on, so the pass returns it to ``new`` and clears the pointer. It re-links
on this same pass if it is still genuinely identical to something; otherwise it
is reviewable again instead of hidden behind a row it does not duplicate.

**Non-comic rows are outside the set entirely** (FRG-SRC-016). Linking exists to
stop the operator reviewing the same comic twice, and a row classified ``other``
— by the classifier or by the operator's own mark — is not review work: parking
it would hide it behind two toggles at once, and letting it be a canonical would
park still-comic twins behind a row the comic view never shows. A row that
becomes non-comic therefore LEAVES the set on the next linking pass, unparked
back to ``new``, by the same machinery that frees a copy whose md5 diverged.

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
from foragerr.sources import repo
from foragerr.sources.models import SourceEntitlementRow

logger = logging.getLogger("foragerr.sources.dedupe")

__all__ = [
    "duplicate_backfill_startup_hook",
    "link_duplicate_entitlements",
]

#: Review states that freeze a set: the operator has decided one of its members.
_DECIDED_STATES = ("matched", "ignored")


async def link_duplicate_entitlements(db, source_id: int | None = None) -> int:
    """Park every unparked, non-opted-out COMIC member of a same-md5 set behind
    its canonical, and unpark every copy whose md5 no longer matches or whose
    classification is no longer ``comic``.

    ``source_id`` bounds the scan to one source (the sync path); ``None`` runs
    the same scan for each source in turn (the startup backfill) rather than
    over the whole table at once, so every read is a keyed range of the
    ``(source_id, md5)`` / ``(source_id, review_status)`` indexes and one store's
    queue never sits in the writer lock for another's sake.

    Returns the number of rows parked.

    One source's pass is ONE write transaction so a set moves together — a
    half-linked set would show the operator a copies chip whose members are
    still counted as pending. The read that decides which sets qualify happens
    inside it, so a concurrent match/ignore either lands before the decision
    (and freezes the set) or after the parking (and is a decision on a canonical
    row, which the set is allowed to carry).
    """
    if source_id is None:
        parked = 0
        for source in await repo.list_sources(db):
            parked += await link_duplicate_entitlements(db, source.id)
        return parked

    parked = 0
    async with db.write_session() as session:
        # Two keyed reads rather than one table scan: the md5-bearing rows are
        # the linking candidates, and the parked rows are re-checked even when
        # their md5 has since been nulled — which is itself an unpark trigger,
        # so those rows cannot be reached by the first read.
        rows = (
            (
                await session.execute(
                    select(SourceEntitlementRow)
                    .where(
                        SourceEntitlementRow.source_id == source_id,
                        SourceEntitlementRow.md5.is_not(None),
                        SourceEntitlementRow.classification == "comic",
                    )
                    .order_by(SourceEntitlementRow.id)
                )
            )
            .scalars()
            .all()
        )
        parked_rows = (
            (
                await session.execute(
                    select(SourceEntitlementRow).where(
                        SourceEntitlementRow.source_id == source_id,
                        SourceEntitlementRow.review_status == "duplicate",
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {row.id: row for row in rows}
        for row in parked_rows:
            by_id.setdefault(row.id, row)
        members_by_id = sorted(by_id.values(), key=lambda row: row.id)
        now = utcnow()

        for copy in members_by_id:
            if copy.review_status != "duplicate":
                continue
            canonical = by_id.get(copy.duplicate_of) if copy.duplicate_of else None
            if (
                canonical is not None
                and copy.classification == "comic"
                and copy.md5
                and copy.md5 == canonical.md5
            ):
                continue
            copy.review_status = "new"
            copy.duplicate_of = None
            copy.updated_at = now

        sets: dict[str, list[SourceEntitlementRow]] = defaultdict(list)
        for row in members_by_id:
            if row.classification != "comic":
                continue  # left the set above; not a candidate to re-enter it
            if not row.md5:
                continue  # an empty string is no more a fingerprint than NULL
            sets[row.md5].append(row)
        for members in sets.values():  # id-ordered: members_by_id was
            if len(members) < 2:
                continue
            if any(member.review_status in _DECIDED_STATES for member in members):
                continue
            canonical = next(
                (m for m in members if m.review_status == "new"), None
            )
            if canonical is None:
                # Every member is parked, so the set has no row the operator can
                # act on. Leave it alone and say so: the unpark pass above should
                # have freed one, and a set that reaches here is hidden entirely.
                logger.warning(
                    "sources.dedupe: md5 set of %d entitlement(s) in source %d "
                    "has no reviewable member; leaving it unchanged",
                    len(members),
                    source_id,
                )
                continue
            for member in members:
                if member.id == canonical.id:
                    continue
                if member.review_status != "new" or member.dedupe_opt_out:
                    continue
                member.review_status = "duplicate"
                member.duplicate_of = canonical.id
                member.updated_at = now
                parked += 1
    if parked:
        logger.info(
            "sources.dedupe: parked %d byte-identical entitlement copy(ies)",
            parked,
        )
    return parked


async def duplicate_backfill_startup_hook(app) -> None:
    """Link pre-existing md5 sets once, at boot (FRG-SRC-015).

    Idempotent: an already-parked row is not re-parked and a restored one
    carries the opt-out flag, so the hook needs no completion marker. Never
    fatal: a failure is logged and the boot continues with the rows unlinked,
    and the next start retries.
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
