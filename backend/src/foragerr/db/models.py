"""ORM models for the command backbone tables (created by migration 0001).

These use the strict/sentinel-free column conventions from
:mod:`foragerr.db.base` (FRG-DB-008): typed timestamps, typed integers, and
sentinel-normalizing text for free-form result fields. The ``error`` column
is deliberately plain TEXT — failure messages are preserved verbatim for the
audit trail (FRG-SCHED-008).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from foragerr.db.base import Base, SentinelFreeText, StrictDateTime, StrictInteger

#: Command lifecycle statuses (FRG-SCHED-001).
COMMAND_STATUSES = ("queued", "started", "completed", "failed", "cancelled")
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class CommandRow(Base):
    """A persisted background command (FRG-SCHED-001/002/003/004)."""

    __tablename__ = "commands"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    priority: Mapped[int] = mapped_column(StrictInteger, nullable=False, default=0)
    workload_class: Mapped[str] = mapped_column(Text, nullable=False, default="default")
    exclusivity_group: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # canonical JSON
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_by: Mapped[str] = mapped_column(Text, nullable=False, default="manual")
    queued_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)
    started_at: Mapped[dt.datetime | None] = mapped_column(StrictDateTime, nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(StrictDateTime, nullable=True)
    result: Mapped[str | None] = mapped_column(SentinelFreeText, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)  # verbatim

    __table_args__ = (
        Index("ix_commands_claim", "status", "workload_class", "priority"),
        Index("ix_commands_dedup", "name", "payload_hash", "status"),
    )


class ScheduledTaskRow(Base):
    """Recurring-task schedule state (FRG-SCHED-006/007)."""

    __tablename__ = "scheduled_tasks"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    interval_seconds: Mapped[int] = mapped_column(StrictInteger, nullable=False)
    last_run: Mapped[dt.datetime | None] = mapped_column(StrictDateTime, nullable=True)


class JobHistoryRow(Base):
    """One row per command execution — the audit trail (FRG-SCHED-008)."""

    __tablename__ = "job_history"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    command_id: Mapped[int | None] = mapped_column(
        StrictInteger, ForeignKey("commands.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_by: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[dt.datetime | None] = mapped_column(StrictDateTime, nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(StrictDateTime, nullable=True)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)  # verbatim

    __table_args__ = (Index("ix_job_history_finished", "finished_at"),)
