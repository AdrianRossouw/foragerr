"""Connect / validate / disconnect + entitlement sync (FRG-SRC-001/002/003/005).

The store-source service layer:

* :func:`connect_source` performs a LIVE order-list validation before persisting
  the cookie — "Connected — N orders" on success, nothing stored on failure
  (FRG-SRC-002).
* :func:`reconnect_source` re-validates a fresh cookie on an ``expired`` source
  and returns it to ``connected`` (FRG-SRC-005).
* :func:`disconnect_source` deletes the credential but keeps every entitlement
  (FRG-SRC-001).
* :func:`run_sync` diffs the Humble order API against known entitlements by the
  store-native key so re-syncs are idempotent, classifies comic/other, keeps
  non-comic items, skips-and-logs malformed/transient orders, and preserves
  partial results — a 401 mid-sync raises :class:`HumbleAuthError` up to the
  caller to flip the source to ``expired`` (no retry storm).

Sync is also where the two m11 review-experience fields land (FRG-SRC-011/012):
each row carries its order's bundle display name (backfilled on re-sync like any
other display detail), and classification is (re-)computed from the CURRENT
format shape combined with the source's CURRENT publisher rules — but only for
rows still in the automatic classifier's hands (``review_status = "new"``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pydantic import BaseModel

from foragerr.db.base import utcnow
from foragerr.sources.classify import (
    NO_PUBLISHER_RULES,
    PublisherRuleSet,
    classify,
)
from foragerr.sources.dedupe import link_duplicate_entitlements
from foragerr.sources.humble import (
    HUMBLE_API_BASE,
    HumbleAuthError,
    HumbleClient,
    HumbleMalformedError,
    HumbleUnavailable,
    ParsedEntitlement,
)
from foragerr.sources.models import SourceEntitlementRow, SourceRow
from foragerr.sources.repo import (
    create_source,
    load_source_settings,
    update_source_settings,
)

logger = logging.getLogger("foragerr.sources.service")


class SourceConnectError(Exception):
    """Connect/reconnect validation failed. ``cause`` is ``auth`` (bad/expired
    cookie) or ``network`` (unreachable/transient) so the API can name it."""

    def __init__(self, message: str, *, cause: str) -> None:
        super().__init__(message)
        self.cause = cause


@dataclass(slots=True)
class SyncResult:
    """The outcome of one entitlement sync run."""

    orders: int = 0
    new_entitlements: int = 0
    updated_entitlements: int = 0
    comic: int = 0
    other: int = 0
    skipped_orders: int = 0
    #: Copies parked behind a byte-identical canonical row this run (FRG-SRC-015).
    duplicates_parked: int = 0
    expired: bool = False
    #: True once at least one order was processed (partial results are kept even
    #: when a later order triggers expiry).
    partial: bool = field(default=False)

    def summary(self) -> str:
        parts = [
            f"{self.orders} order(s)",
            f"{self.new_entitlements} new",
            f"{self.updated_entitlements} updated",
            f"{self.comic} comic",
            f"{self.other} other",
        ]
        if self.skipped_orders:
            parts.append(f"{self.skipped_orders} order(s) skipped")
        if self.duplicates_parked:
            parts.append(f"{self.duplicates_parked} duplicate(s) parked")
        if self.expired:
            parts.append("session expired mid-sync")
        return ", ".join(parts)


def _cookie_of(settings: BaseModel) -> str:
    """The revealed session cookie from a validated Humble settings model."""
    return settings.session_cookie.get_secret_value()


async def _validate_cookie(client: HumbleClient) -> int:
    """Run the live order-list validation call; return the order count or raise
    :class:`SourceConnectError` with a named cause (FRG-SRC-002)."""
    try:
        gamekeys = await client.list_gamekeys()
    except HumbleAuthError as exc:
        raise SourceConnectError(
            "the Humble session cookie was rejected — it is invalid or expired; "
            "re-copy it from a fresh logged-in browser session",
            cause="auth",
        ) from exc
    except (HumbleUnavailable, HumbleMalformedError) as exc:
        raise SourceConnectError(
            f"could not reach Humble to validate the cookie: {exc}",
            cause="network",
        ) from exc
    return len(gamekeys)


async def connect_source(
    db,
    factory,
    *,
    source_type: str,
    name: str,
    settings: BaseModel,
    auto_sync: bool = False,
    min_interval: float,
    base_url: str = HUMBLE_API_BASE,
) -> tuple[SourceRow, int]:
    """Validate the cookie live, then persist the source (FRG-SRC-001/002).

    Returns ``(row, order_count)``. On validation failure NOTHING is persisted
    and :class:`SourceConnectError` names the cause."""
    async with HumbleClient(
        factory,
        _cookie_of(settings),
        source_id=0,
        min_interval=min_interval,
        base_url=base_url,
    ) as client:
        order_count = await _validate_cookie(client)
    row = await create_source(
        db,
        source_type=source_type,
        name=name,
        settings=settings,
        connection_state="connected",
        auto_sync=auto_sync,
    )
    return row, order_count


async def reconnect_source(
    db,
    factory,
    source: SourceRow,
    *,
    settings: BaseModel,
    min_interval: float,
    base_url: str = HUMBLE_API_BASE,
) -> tuple[SourceRow, int]:
    """Re-validate a fresh cookie on an existing source and return it to
    ``connected`` (FRG-SRC-005 reconnect). Nothing changes on failure."""
    async with HumbleClient(
        factory,
        _cookie_of(settings),
        source_id=source.id,
        min_interval=min_interval,
        base_url=base_url,
    ) as client:
        order_count = await _validate_cookie(client)
    row = await update_source_settings(
        db, source.id, settings=settings, connection_state="connected"
    )
    assert row is not None  # caller proved the row exists
    return row, order_count


async def run_sync(
    db,
    factory,
    source: SourceRow,
    *,
    min_interval: float,
    base_url: str = HUMBLE_API_BASE,
    publisher_rules: PublisherRuleSet = NO_PUBLISHER_RULES,
) -> SyncResult:
    """Diff the Humble order API against known entitlements (FRG-SRC-003).

    Persists per order (partial results survive a mid-sync failure). A 401 at any
    point stops the run and RAISES :class:`HumbleAuthError` so the caller flips
    the source to ``expired`` (FRG-SRC-005); a transient/malformed order is
    skipped-and-logged and the run continues.

    ``publisher_rules`` is the library-wide non-comic rule set (FRG-SRC-012),
    compiled ONCE by the caller from ``Settings.non_comic_publishers`` and applied
    to every entitlement of the run — it is not source-scoped state, so it is not
    read from the source's settings envelope. Omitted, it is empty: pure
    format-shape classification."""
    settings = load_source_settings(source.type, source.settings)
    result = SyncResult()
    async with HumbleClient(
        factory,
        _cookie_of(settings),
        source_id=source.id,
        min_interval=min_interval,
        base_url=base_url,
    ) as client:
        gamekeys = await client.list_gamekeys()  # 401 here → caller marks expired
        try:
            for gamekey in gamekeys:
                try:
                    entitlements = await client.fetch_order(gamekey)
                except HumbleAuthError:
                    # Mid-sync expiry: stop, keep everything already persisted.
                    result.expired = True
                    raise
                except (HumbleUnavailable, HumbleMalformedError) as exc:
                    logger.warning(
                        "sync: skipping order %s (%s); partial results kept",
                        gamekey,
                        exc,
                    )
                    result.skipped_orders += 1
                    continue
                await _persist_order(
                    db, source.id, entitlements, result, publisher_rules=publisher_rules
                )
                result.orders += 1
                result.partial = True
        finally:
            # md5 linking (FRG-SRC-015) runs ONCE per sync over the source's
            # rows, not per order: a per-order pass would re-scan the whole
            # inventory for every order, and a set can span orders anyway (the
            # same file bought in two bundles is the case it exists for). In the
            # ``finally`` so a mid-sync expiry still collapses whatever the run
            # persisted, matching the partial-results contract above.
            if result.orders:
                result.duplicates_parked = await link_duplicate_entitlements(
                    db, source.id
                )
    return result


async def _persist_order(
    db,
    source_id: int,
    entitlements: list[ParsedEntitlement],
    result: SyncResult,
    *,
    publisher_rules: PublisherRuleSet = NO_PUBLISHER_RULES,
) -> None:
    """Upsert one order's entitlements by the store-native key (idempotent).

    A new item is inserted as ``new`` with NULL proposed/actual match fields
    (worker A2 fills the proposed match). An existing item's DISPLAY fields are
    refreshed but its review status, download state, and operator match decisions
    are PRESERVED — a re-sync never resets a decision or creates a duplicate.

    **Classification is re-derived every sync** from the item's CURRENT formats
    and the CURRENT library-wide publisher rules (FRG-SRC-012) — but written back
    ONLY while the row is still ``review_status = "new"``. That is what makes a
    rule change take effect in both directions on the next sync (added rule:
    comic → other; removed rule: other → comic) while leaving every decided row
    exactly where the operator put it: a matched or ignored row is an operator
    decision, and a later rule edit must never silently move it between the
    review buckets it was decided in.

    The bundle display name is a display detail like the title, so it is
    refreshed on every row (backfilling pre-0026 rows on their next sync) — but
    only FORWARD: a payload with no bundle name leaves a previously captured one
    in place rather than nulling it.
    """
    from sqlalchemy import select

    now = utcnow()
    async with db.write_session() as session:
        for ent in entitlements:
            classification = classify(
                list(ent.options),
                publisher=ent.publisher,
                publisher_rules=publisher_rules,
            )
            existing = (
                await session.execute(
                    select(SourceEntitlementRow).where(
                        SourceEntitlementRow.source_id == source_id,
                        SourceEntitlementRow.gamekey == ent.gamekey,
                        SourceEntitlementRow.machine_name == ent.machine_name,
                    )
                )
            ).scalar_one_or_none()
            # The run counters report what the row ACTUALLY carries after this
            # sync — a decided row keeps its stored classification, so counting
            # the freshly-derived value there would over-report a rule's effect.
            effective = (
                classification
                if existing is None or existing.review_status == "new"
                else existing.classification
            )
            if effective == "comic":
                result.comic += 1
            else:
                result.other += 1
            preferred = ent.preferred
            formats_json = _formats_json(ent)
            if existing is None:
                session.add(
                    SourceEntitlementRow(
                        source_id=source_id,
                        gamekey=ent.gamekey,
                        machine_name=ent.machine_name,
                        human_name=ent.human_name,
                        publisher=ent.publisher,
                        bundle_human_name=ent.bundle_human_name,
                        classification=classification,
                        review_status="new",
                        download_state=None,
                        preferred_format=preferred.format if preferred else None,
                        md5=preferred.md5 if preferred else None,
                        file_size=preferred.file_size if preferred else None,
                        filename=preferred.filename if preferred else None,
                        formats_json=formats_json,
                        proposed_series_id=None,  # worker A2 seam
                        proposed_match_json=None,  # worker A2 seam
                        matched_series_id=None,  # review-workflow seam
                        created_at=now,
                        updated_at=now,
                    )
                )
                result.new_entitlements += 1
            else:
                # Refresh display/format fields only; preserve operator decisions.
                existing.human_name = ent.human_name
                existing.publisher = ent.publisher
                # A payload that simply OMITS the bundle name is not evidence
                # that the row has none: Humble's order shapes vary, and a
                # single such response would otherwise null a name captured on
                # an earlier sync — silently emptying the "select bundle"
                # affordance for those rows (FRG-SRC-011). Refresh forward only.
                existing.bundle_human_name = (
                    ent.bundle_human_name or existing.bundle_human_name
                )
                if existing.review_status == "new":
                    # Still the automatic classifier's row → re-derive it from
                    # the current formats + rules (FRG-SRC-012, both directions).
                    existing.classification = classification
                existing.preferred_format = preferred.format if preferred else None
                existing.md5 = preferred.md5 if preferred else None
                existing.file_size = preferred.file_size if preferred else None
                existing.filename = preferred.filename if preferred else None
                existing.formats_json = formats_json
                existing.updated_at = now
                result.updated_entitlements += 1


def _formats_json(ent: ParsedEntitlement) -> str:
    """The full download-option list as canonical JSON (worker A2 grabs a
    non-preferred format from this without re-classifying)."""
    import json

    return json.dumps(
        [
            {
                "name": opt.format,
                "platform": opt.platform,
                "md5": opt.md5,
                "file_size": opt.file_size,
                "filename": opt.filename,
            }
            for opt in ent.options
        ],
        sort_keys=True,
    )


__all__ = [
    "SourceConnectError",
    "SyncResult",
    "connect_source",
    "disconnect_source",
    "reconnect_source",
    "run_sync",
]


async def disconnect_source(db, source_id: int) -> SourceRow | None:
    """Disconnect: delete the credential, keep entitlements (FRG-SRC-001)."""
    from foragerr.sources.repo import set_connection_state

    return await set_connection_state(
        db, source_id, "disconnected", clear_credential=True
    )
