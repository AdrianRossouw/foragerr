"""Async SQLite engine, sessions, and single-writer discipline.

Implements FRG-DB-001 (single DB file under the config dir), FRG-DB-005
(per-connection PRAGMAs: WAL, busy_timeout, foreign_keys, synchronous=NORMAL),
FRG-DB-006 (all writes serialized through ``write_session()`` with bounded
busy retry — a raw "database is locked" error never reaches a caller), and
FRG-DB-007 (atomic commit/rollback with domain events published only after a
successful commit).

Usage::

    db = Database(settings)
    async with db.read_session() as session:      # readers, WAL-concurrent
        ...
    async with db.write_session() as session:      # ONE writer at a time
        session.add(row)
        queue_event(session, SomethingHappened())  # delivered post-commit

``write_session()`` is NOT re-entrant — never nest it (asyncio.Lock is not
reentrant and nesting would deadlock).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError, PendingRollbackError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from foragerr.config import Settings

logger = logging.getLogger("foragerr.db")

DB_FILENAME = "foragerr.db"

_LOCKED_MARKERS = ("database is locked", "database table is locked")


def database_path(config_dir: Path) -> Path:
    """The single SQLite database file under the config dir (FRG-DB-001)."""
    return config_dir / DB_FILENAME


class DatabaseBusyError(RuntimeError):
    """A write could not complete within the bounded busy-retry budget.

    Distinct, typed replacement for raw SQLITE_BUSY errors (FRG-DB-006).
    """


def _is_locked_error(exc: BaseException) -> bool:
    while exc is not None:
        if any(marker in str(exc) for marker in _LOCKED_MARKERS):
            return True
        exc = exc.__cause__  # unwrap SQLAlchemy DBAPI wrapping
    return False


class Database:
    """Owns the async engine, session factories, and the write lock."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        db_path: Path | None = None,
        busy_timeout_ms: int | None = None,
        commit_retry_attempts: int = 4,
        commit_retry_base_delay: float = 0.05,
        event_publisher: Callable[[Any], None] | None = None,
    ) -> None:
        if db_path is None:
            if settings is None:
                raise ValueError("either settings or db_path is required")
            db_path = database_path(settings.config_dir)
        self.db_path = db_path
        self.busy_timeout_ms = (
            busy_timeout_ms
            if busy_timeout_ms is not None
            else (settings.db_busy_timeout_ms if settings else 5000)
        )
        self._commit_retry_attempts = commit_retry_attempts
        self._commit_retry_base_delay = commit_retry_base_delay
        #: Set post-construction by the sched area: called once per queued
        #: domain event, strictly after a successful commit (FRG-DB-007).
        self.event_publisher = event_publisher

        self._engine: AsyncEngine = create_async_engine(
            f"sqlite+aiosqlite:///{self.db_path}"
        )
        self._install_pragmas(self._engine, self.busy_timeout_ms)
        self._sessions = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )
        self._write_lock = asyncio.Lock()

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @staticmethod
    def _install_pragmas(engine: AsyncEngine, busy_timeout_ms: int) -> None:
        """Apply the required PRAGMAs to EVERY pooled connection (FRG-DB-005)."""

        @event.listens_for(engine.sync_engine, "connect")
        def _on_connect(dbapi_conn: Any, _record: Any) -> None:
            cursor = dbapi_conn.cursor()
            for pragma in (
                f"PRAGMA busy_timeout={busy_timeout_ms}",
                "PRAGMA journal_mode=WAL",
                "PRAGMA foreign_keys=ON",
                "PRAGMA synchronous=NORMAL",
            ):
                cursor.execute(pragma)
            cursor.close()

    @asynccontextmanager
    async def read_session(self) -> AsyncIterator[AsyncSession]:
        """A read-only session; WAL keeps readers unblocked by the writer."""
        async with self._sessions() as session:
            yield session

    @asynccontextmanager
    async def write_session(self) -> AsyncIterator[AsyncSession]:
        """The single writer path (FRG-DB-006/007).

        - Serializes all writers through one asyncio lock.
        - Commits on clean exit, rolls back (fully) on any exception.
        - Translates residual locked errors into :class:`DatabaseBusyError`.
        - Publishes events queued via :func:`queue_event` only after commit.
        """
        events: list[Any] = []
        async with self._write_lock:
            session = self._sessions()
            session.info["post_commit_events"] = events
            try:
                yield session
                await self._commit_with_retry(session)
            except DatabaseBusyError:
                raise
            except OperationalError as exc:
                await session.rollback()
                if _is_locked_error(exc):
                    raise DatabaseBusyError(
                        f"database stayed locked beyond the busy budget: {exc}"
                    ) from exc
                raise
            except BaseException:
                await session.rollback()
                raise
            finally:
                await session.close()
        # The lock is released and the commit succeeded: deliver events.
        if events and self.event_publisher is not None:
            for evt in events:
                self.event_publisher(evt)

    async def _commit_with_retry(self, session: AsyncSession) -> None:
        """Commit with bounded backoff on residual SQLITE_BUSY (FRG-DB-006)."""
        delay = self._commit_retry_base_delay
        last_exc: BaseException | None = None
        for _attempt in range(self._commit_retry_attempts):
            try:
                await session.commit()
                return
            except PendingRollbackError as exc:
                last_exc = exc
                break  # transaction is dead; retrying commit cannot help
            except OperationalError as exc:
                if not _is_locked_error(exc):
                    await session.rollback()
                    raise
                last_exc = exc
                logger.warning(
                    "db: commit hit a locked database; retrying in %.2fs", delay
                )
                await asyncio.sleep(delay)
                delay *= 2
        await session.rollback()
        raise DatabaseBusyError(
            f"write did not commit after {self._commit_retry_attempts} attempts: "
            f"{last_exc}"
        ) from last_exc

    async def wal_checkpoint(self) -> None:
        """Fold the WAL back into the main database file (shutdown path)."""
        async with self._engine.connect() as conn:
            await conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))

    async def close(self) -> None:
        """WAL-checkpoint and dispose the engine (FRG-DEP-008 shutdown half)."""
        try:
            await self.wal_checkpoint()
        except Exception:  # pragma: no cover - best-effort on shutdown
            logger.exception("db: WAL checkpoint on shutdown failed")
        await self._engine.dispose()

    async def health(self) -> dict[str, Any]:
        """Component health for /health (api area consumes this)."""
        try:
            async with self._sessions() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:
            return {"status": "down", "error": str(exc)}
        return {"status": "up", "path": str(self.db_path)}


def queue_event(session: AsyncSession, event_obj: Any) -> None:
    """Queue a domain event for post-commit publication (FRG-DB-007).

    Only valid inside a ``write_session()`` block; if the transaction rolls
    back the event is discarded and never published.
    """
    events = session.info.get("post_commit_events")
    if events is None:
        raise RuntimeError("queue_event() is only valid inside write_session()")
    events.append(event_obj)
