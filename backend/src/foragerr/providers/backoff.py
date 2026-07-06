"""The generic escalating failure back-off ladder (FRG-IDX-010, FRG-NFR-005).

One persisted cool-down mechanism, keyed by ``(provider_type, provider_id)``,
consulted by *every* remote-provider fetch path. On repeated failure a provider
walks an escalating ladder (1 m → 5 m → 15 m → 30 m → 1 h → 3 h → 6 h → 12 h →
24 h); a Retry-After header or an auth/limit failure fast-forwards the ladder
instead of stepping one rung; a single success resets it. The state lives in
the ``provider_backoff`` table so a restart never wipes a ban-avoidance
cool-down (FRG-NFR-005 "persist backoff state").

Generic by construction (design decision 6): the indexer area keys rows with
``PROVIDER_INDEXER``; change 5's download clients and DDL provider reuse the
same table and API with their own ``provider_type`` — no schema change.

Every fetch path MUST call :meth:`ProviderBackoff.status` first and skip+log a
provider whose status is ``active``; on the request outcome it calls
:meth:`record_success` or :meth:`record_failure`.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from sqlalchemy import Text, select
from sqlalchemy.orm import Mapped, mapped_column

from foragerr.db.base import Base, StrictDateTime, StrictInteger, utcnow

if TYPE_CHECKING:  # avoid an import cycle; only a type reference
    from foragerr.db.engine import Database

logger = logging.getLogger("foragerr.providers.backoff")

#: Provider-type discriminators (the ``provider_type`` key half). Indexers are
#: owned here; the others are declared now so change 5 adds rows, not a schema
#: or enum change (FRG-IDX-010 "generic over provider type").
PROVIDER_INDEXER = "indexer"
PROVIDER_DOWNLOAD_CLIENT = "download_client"
PROVIDER_DDL = "ddl"

#: The escalation ladder (FRG-IDX-010): index 0 is "no back-off" (0 s); each
#: consecutive failure steps one rung, capped at 24 h. Copied close to Sonarr's
#: EscalationBackOff (sonarr-architecture.md §2.6).
LADDER: tuple[dt.timedelta, ...] = (
    dt.timedelta(0),
    dt.timedelta(minutes=1),
    dt.timedelta(minutes=5),
    dt.timedelta(minutes=15),
    dt.timedelta(minutes=30),
    dt.timedelta(hours=1),
    dt.timedelta(hours=3),
    dt.timedelta(hours=6),
    dt.timedelta(hours=12),
    dt.timedelta(hours=24),
)
MAX_LEVEL = len(LADDER) - 1

#: A fast-forward (Retry-After / auth / request-limit failure) jumps at least to
#: this rung (1 h) rather than stepping one level — a provider that told us to
#: back off, or rejected our credentials, is not worth hammering on the 1 m rung.
FAST_FORWARD_MIN_LEVEL = 5


class ProviderBackoffRow(Base):
    """Persisted per-provider back-off state (survives restart, FRG-NFR-005).

    Composite primary key ``(provider_type, provider_id)`` — the generic key
    that lets download clients and DDL share the table (FRG-IDX-010).
    """

    __tablename__ = "provider_backoff"

    provider_type: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_id: Mapped[int] = mapped_column(StrictInteger, primary_key=True)
    level: Mapped[int] = mapped_column(StrictInteger, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(
        StrictInteger, nullable=False, default=0
    )
    next_allowed_at: Mapped[dt.datetime | None] = mapped_column(
        StrictDateTime, nullable=True
    )
    last_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_failure_at: Mapped[dt.datetime | None] = mapped_column(
        StrictDateTime, nullable=True
    )
    updated_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)


@dataclass(frozen=True, slots=True)
class BackoffStatus:
    """A snapshot of one provider's back-off state at a given instant."""

    provider_type: str
    provider_id: int
    #: True when the provider is inside its cool-down window (skip the fetch).
    active: bool
    level: int
    failure_count: int
    next_allowed_at: dt.datetime | None
    last_reason: str | None
    remaining_seconds: float
    #: When the most recent failure was recorded (for the health surface,
    #: FRG-NFR-011 "last-failure timestamp"); ``None`` for an untracked provider.
    last_failure_at: dt.datetime | None = None

    @property
    def healthy(self) -> bool:
        """No recorded failures outstanding — the inverse of a tracked row."""
        return self.level == 0 and not self.active


class ProviderBackoff:
    """The back-off ladder over a :class:`~foragerr.db.engine.Database`.

    ``clock`` is injectable for deterministic tests; production passes none and
    gets naive-UTC wall time. All mutations go through the single-writer
    ``write_session`` (FRG-DB-006); status reads use a read session.
    """

    def __init__(
        self, db: "Database", *, clock: Callable[[], dt.datetime] = utcnow
    ) -> None:
        self._db = db
        self._clock = clock

    async def status(
        self, provider_type: str, provider_id: int
    ) -> BackoffStatus:
        """The current status; ``active`` True means the caller MUST skip."""
        async with self._db.read_session() as session:
            row = await session.get(
                ProviderBackoffRow, (provider_type, provider_id)
            )
            return self._to_status(provider_type, provider_id, row)

    async def is_backing_off(self, provider_type: str, provider_id: int) -> bool:
        """Convenience predicate: is this provider inside its cool-down now?"""
        return (await self.status(provider_type, provider_id)).active

    async def record_success(
        self, provider_type: str, provider_id: int
    ) -> None:
        """Reset the provider to no back-off (FRG-IDX-010 / FRG-NFR-005).

        A single success fully clears the ladder — the row is deleted so the
        provider is immediately eligible again.
        """
        async with self._db.write_session() as session:
            row = await session.get(
                ProviderBackoffRow, (provider_type, provider_id)
            )
            if row is not None:
                await session.delete(row)
                logger.info(
                    "provider back-off reset after success",
                    extra={"provider_type": provider_type, "provider_id": provider_id},
                )

    async def record_failure(
        self,
        provider_type: str,
        provider_id: int,
        *,
        reason: str,
        retry_after: float | None = None,
        fast_forward: bool = False,
    ) -> BackoffStatus:
        """Escalate the ladder for one failed request.

        ``fast_forward`` (auth or request-limit failures) jumps to at least
        :data:`FAST_FORWARD_MIN_LEVEL` rather than stepping one rung.
        ``retry_after`` (seconds, from a Retry-After header) floors the
        resulting cool-down so an explicit server instruction is always
        honored (FRG-IDX-010 fast-forward scenario).
        """
        now = self._clock()
        async with self._db.write_session() as session:
            row = await session.get(
                ProviderBackoffRow, (provider_type, provider_id)
            )
            if row is None:
                row = ProviderBackoffRow(
                    provider_type=provider_type,
                    provider_id=provider_id,
                    level=0,
                    failure_count=0,
                    updated_at=now,
                )
                session.add(row)

            if fast_forward or retry_after is not None:
                new_level = max(row.level + 1, FAST_FORWARD_MIN_LEVEL)
            else:
                new_level = row.level + 1
            new_level = min(new_level, MAX_LEVEL)

            delay = LADDER[new_level]
            if retry_after is not None and retry_after > 0:
                delay = max(delay, dt.timedelta(seconds=retry_after))

            row.level = new_level
            row.failure_count += 1
            row.next_allowed_at = now + delay
            row.last_reason = reason
            row.last_failure_at = now
            row.updated_at = now
            status = self._to_status(provider_type, provider_id, row, now=now)
        logger.warning(
            "provider backing off",
            extra={
                "provider_type": provider_type,
                "provider_id": provider_id,
                "level": status.level,
                "backoff_seconds": round(status.remaining_seconds, 1),
                "reason": reason,
            },
        )
        return status

    async def health(
        self, provider_type: str | None = None
    ) -> list[BackoffStatus]:
        """Every tracked provider's status, for the health surface (FRG-IDX-010
        "shows them in health"). Optionally filtered to one ``provider_type``."""
        stmt = select(ProviderBackoffRow)
        if provider_type is not None:
            stmt = stmt.where(ProviderBackoffRow.provider_type == provider_type)
        async with self._db.read_session() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [
            self._to_status(row.provider_type, row.provider_id, row) for row in rows
        ]

    def _to_status(
        self,
        provider_type: str,
        provider_id: int,
        row: ProviderBackoffRow | None,
        *,
        now: dt.datetime | None = None,
    ) -> BackoffStatus:
        if row is None:
            return BackoffStatus(
                provider_type=provider_type,
                provider_id=provider_id,
                active=False,
                level=0,
                failure_count=0,
                next_allowed_at=None,
                last_reason=None,
                remaining_seconds=0.0,
            )
        now = now or self._clock()
        remaining = 0.0
        active = False
        if row.next_allowed_at is not None and now < row.next_allowed_at:
            remaining = (row.next_allowed_at - now).total_seconds()
            active = True
        return BackoffStatus(
            provider_type=row.provider_type,
            provider_id=row.provider_id,
            active=active,
            level=row.level,
            failure_count=row.failure_count,
            next_allowed_at=row.next_allowed_at,
            last_reason=row.last_reason,
            remaining_seconds=remaining,
            last_failure_at=row.last_failure_at,
        )
