"""Structured logging with secret redaction (FRG-DEP-006, FRG-NFR-008).

Design (m1-foundation, decision 8): stdlib logging, key-value structured
formatter (no extra dependency), a stdout handler plus a size-rotated file
handler at ``<config_dir>/logs/foragerr.log``. A redaction ``logging.Filter``
masks (a) every registered secret value and (b) api_key/apikey-shaped query
parameter values in messages, args, and formatted exception text. The filter
is installed on BOTH handlers so no record reaches an output unmasked.

Secret values self-register at config-load time via :func:`register_secret`,
so later changes inherit redaction for free.
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

MASK = "***REDACTED***"

LOG_FILENAME = "foragerr.log"

#: Registered secret values (populated at config-load time). Module-level by
#: design: redaction must be global no matter how many apps/settings exist.
_SECRETS: set[str] = set()

#: Credential-shaped query parameters masked even when the value was never
#: registered as a config secret (FRG-NFR-008, third scenario).
_KEY_PARAM_RE = re.compile(
    r"(?i)\b(api_?key|token|password|passwd|secret|access_key)=([^&\s\"'<>]+)"
)


def register_secret(value: str) -> None:
    """Register a secret value so the redaction filter masks it everywhere."""
    if value:
        _SECRETS.add(value)


def clear_secrets() -> None:
    """Forget all registered secrets (test isolation hook)."""
    _SECRETS.clear()


def redact(text: str) -> str:
    """Return ``text`` with registered secrets and key-shaped params masked."""
    for secret in _SECRETS:
        if secret in text:
            text = text.replace(secret, MASK)
    return _KEY_PARAM_RE.sub(rf"\1={MASK}", text)


class RedactionFilter(logging.Filter):
    """Masks secrets in the record message, args, and exception text.

    The record is mutated before formatting: the final message (with args
    already interpolated) and the formatted traceback are both redacted, so
    a secret can never reach the handler's output regardless of whether it
    arrived inline, as a ``%s`` argument, or inside an exception. Idempotent,
    so installing it on multiple handlers is safe.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # malformed format string — degrade, never drop
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(str(record.stack_info))
        return True


#: LogRecord attributes that are not caller-supplied ``extra`` fields.
_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "taskName",
}


def _quote(value: str) -> str:
    """Quote a value for key=value output if it needs it (shlex-parseable)."""
    if value and not re.search(r'[\s"\'\\=]', value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class KeyValueFormatter(logging.Formatter):
    """key=value structured formatter: timestamp, level, logger, message,
    plus any caller-supplied ``extra`` fields (FRG-DEP-006)."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        )
        parts = [
            f"ts={ts}",
            f"level={record.levelname}",
            f"logger={_quote(record.name)}",
            f"msg={_quote(record.getMessage())}",
        ]
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                parts.append(f"{key}={_quote(str(value))}")
        line = " ".join(parts)
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            line = f"{line}\n{record.exc_text}"
        if record.stack_info:
            line = f"{line}\n{record.stack_info}"
        return line


def setup_logging(
    config_dir: Path,
    level: str = "INFO",
    max_bytes: int = 10_000_000,
    backup_count: int = 5,
) -> None:
    """Configure root logging: structured stdout + size-rotated file handler.

    Idempotent — previously installed foragerr handlers are replaced, so
    repeated ``create_app()`` calls never duplicate output. Takes primitives
    (not a Settings object) to avoid a config<->logging import cycle.
    """
    logs_dir = config_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_foragerr", False):
            root.removeHandler(handler)
            handler.close()

    formatter = KeyValueFormatter()
    redaction = RedactionFilter()
    stdout_handler: logging.Handler = logging.StreamHandler(sys.stdout)
    file_handler: logging.Handler = RotatingFileHandler(
        logs_dir / LOG_FILENAME,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    for handler in (stdout_handler, file_handler):
        handler.setFormatter(formatter)
        handler.addFilter(redaction)  # on BOTH handlers (FRG-NFR-008)
        handler._foragerr = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.setLevel(level.upper())
