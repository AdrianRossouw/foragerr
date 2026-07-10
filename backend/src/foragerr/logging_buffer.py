"""In-memory ring-buffer log capture backing ``GET /api/v1/log``
(FRG-API-021, FRG-NFR-015).

Design (m4-logs-viewer, decisions 1 and 3): a bounded
``collections.deque`` behind a dedicated ``logging.Handler`` attached to the
root logger — O(1) append, zero I/O in the logging hot path, a restart
clears it (container stdout stays the durable log per
``foragerr.logging``).

Ordering guarantee (redaction-before-buffer): :func:`install_log_buffer` is
called from ``create_app()`` AFTER ``foragerr.logging.setup_logging`` has
configured the stdout/file handlers, and the handler it installs carries its
OWN :class:`~foragerr.logging.RedactionFilter` instance. Python's logging
``Handler.handle()`` always runs ``self.filter(record)`` immediately before
``self.emit(record)`` for THAT handler — so regardless of how many other
handlers are on the root logger, or in what order they run, this handler's
own filter masks the record before ``emit`` (and therefore before the
record ever reaches the deque). A record can only be buffered in its
already-redacted form; the API can never serve a raw registered secret.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from foragerr.logging import RedactionFilter

__all__ = [
    "BufferedLogRecord",
    "RingBufferHandler",
    "get_log_buffer_handler",
    "install_log_buffer",
]


@dataclass(frozen=True, slots=True)
class BufferedLogRecord:
    """One captured, already-redacted log record."""

    time: datetime
    level: str
    logger: str
    message: str


class RingBufferHandler(logging.Handler):
    """Appends formatted, redacted records to a bounded deque.

    No I/O in ``emit()``: an append to a ``deque(maxlen=...)`` is O(1) and
    self-evicting (the oldest record is dropped on overflow, FRG-NFR-015).
    Handlers are invoked under the stdlib logging module lock, so the deque
    append is already serialized against concurrent log calls — no extra
    locking is needed here.
    """

    def __init__(self, maxlen: int) -> None:
        super().__init__()
        self._records: deque[BufferedLogRecord] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:  # malformed format string — degrade, never raise
            message = str(record.msg)
        if record.exc_text:
            message = f"{message}\n{record.exc_text}"
        elif record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        self._records.append(
            BufferedLogRecord(
                time=datetime.fromtimestamp(record.created, tz=timezone.utc),
                level=record.levelname,
                logger=record.name,
                message=message,
            )
        )

    def snapshot(self) -> list[BufferedLogRecord]:
        """A stable point-in-time copy, oldest first (natural append order)."""
        return list(self._records)


def install_log_buffer(maxlen: int) -> RingBufferHandler:
    """Attach a fresh :class:`RingBufferHandler` to the root logger.

    Call AFTER ``foragerr.logging.setup_logging`` (see module docstring for
    why that ordering guarantees redaction-before-buffer). Idempotent like
    ``setup_logging``: any previously-installed ring-buffer handler is
    removed first, so repeated ``create_app()`` calls (tests) never
    accumulate handlers or leak buffered records between apps. Marked
    ``_foragerr = True`` so the shared test-isolation fixture that sweeps
    foragerr-owned handlers also cleans this one up.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, RingBufferHandler):
            root.removeHandler(handler)
            handler.close()
    handler = RingBufferHandler(maxlen)
    handler.addFilter(RedactionFilter())
    handler._foragerr = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    return handler


def get_log_buffer_handler() -> RingBufferHandler | None:
    """The currently-installed ring-buffer handler, if any."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, RingBufferHandler):
            return handler
    return None
