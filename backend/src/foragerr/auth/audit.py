"""Structured authentication audit events (FRG-AUTH-009).

One helper — :func:`audit_event` — writes every authentication-relevant event to
the ``foragerr.auth`` logger in a fixed ``<event> key=value …`` shape, so the
System → Logs viewer shows and filters them with no frontend change. Events carry
the source IP and surface and NEVER any credential material. The one
attacker-controlled string that may appear is the submitted username, and it is
control-character-stripped and length-capped here (log-injection hardening): a
crafted username can neither break the log line nor forge a second event.

Event vocabulary (the ad-hoc lines from m8-auth-core / m8-keys-opds migrate into
this shape): ``auth.login.success``/``.failure``, ``auth.logout``,
``auth.password_changed``, ``auth.opds_password_changed``, ``auth.opds_success``,
``auth.opds_failure``, ``auth.apikey_failure``, ``auth.apikey_source_seen``,
``auth.apikey_rotated``, ``auth.reauth_failed``, ``auth.backoff_triggered``,
``auth.reseed``.
"""

from __future__ import annotations

import logging
from typing import Any

from starlette.requests import HTTPConnection

logger = logging.getLogger("foragerr.auth")

#: Length cap on any client-controlled string before it reaches a log line. A
#: real username is far shorter; a longer value is abuse or a bug, and capping it
#: bounds the log line regardless.
MAX_FIELD_LENGTH = 64


def sanitize(value: str) -> str:
    """Strip control characters and cap the length of a client-controlled string.

    Removes every C0/C1 control character (newlines, carriage returns, ANSI
    escape introducers, NUL, …) so the value cannot inject a line break or a
    forged event into the fixed ``key=value`` line, then truncates to
    :data:`MAX_FIELD_LENGTH`."""
    stripped = "".join(ch for ch in value if ch.isprintable() or ch == " ")
    return stripped[:MAX_FIELD_LENGTH]


def _client_ip(request: HTTPConnection | None) -> str:
    """The direct-connection client IP (``X-Forwarded-For`` is not trusted)."""
    if request is None:
        return "unknown"
    client = request.client
    return client.host if client is not None else "unknown"


def _render(value: Any) -> str:
    if isinstance(value, str):
        return sanitize(value)
    return str(value)


def audit_event(
    event: str,
    request: HTTPConnection | None,
    surface: str | None = None,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit one structured audit event on the ``foragerr.auth`` logger.

    ``surface`` and the source IP are always included; ``fields`` carry
    event-specifics. Every string value is sanitized — never pass password or key
    material. The message is pre-rendered (no ``%`` args) so a ``%`` inside a
    username cannot trigger interpolation."""
    parts = [f"ip={_client_ip(request)}"]
    if surface is not None:
        parts.append(f"surface={surface}")
    for key, value in fields.items():
        parts.append(f"{key}={_render(value)}")
    logger.log(level, f"{event} {' '.join(parts)}")


__all__ = ["MAX_FIELD_LENGTH", "audit_event", "sanitize"]
