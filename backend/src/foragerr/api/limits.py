"""Listener inbound request resource limits (FRG-NFR-014).

A single pure-ASGI middleware installed in :func:`foragerr.api.register_api`
so it wraps every mounted route (``/api/v1``, ``/opds``, ``/health``, the SPA
root). It runs on the **HTTP scope only** — the ``websocket`` and ``lifespan``
scopes are passed through untouched — so the request timeout and body cap can
never touch the long-lived WebSocket (that surface is hardened separately in
:mod:`foragerr.ws`). Four controls, all configurable with generous documented
defaults (see :mod:`foragerr.config`):

- **Header size cap** (``listener_max_header_bytes``): a request whose combined
  header bytes exceed the cap is rejected with **431** before a handler runs.
- **Per-client rate cap** (``listener_rate_max_requests`` per
  ``listener_rate_window_seconds``, ``0`` disables): a peer address exceeding
  the budget in the window gets **429** + ``Retry-After``. Keyed by peer
  address with a bounded (LRU-capped) client table so the limiter itself can
  never grow unboundedly. A single-user-tailnet DoS safety valve, not
  throttling or access control.
- **Body size cap** (``listener_max_body_bytes``): a ``Content-Length`` over
  the cap is rejected with **413** immediately; a chunked / absent / lying
  ``Content-Length`` is caught by a streaming byte counter that aborts at the
  cap with **413**, so no unbounded body buffer ever accrues.
- **Request timeout** (``listener_request_timeout_seconds``): the handler is
  bounded on **time-to-first-response-byte**. A handler that produces no
  response within the timeout is cancelled (releasing the worker) and answered
  with a bounded **503**. Once the response has started the timeout is dropped,
  so a deliberately-streaming response (an OPDS file download, an SPA asset) is
  never truncated — the correct semantics for "how long may a handler run
  before responding" rather than "how long may a download take".

Any request-sourced value this middleware writes toward the structured logs
(method, path, query in its own over-limit warnings) passes through the
FRG-NFR-012 control-character sanitizer first, so a CR/LF-bearing request can
never forge a log line (the request-sourced arm of RISK-014).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections import OrderedDict, deque

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from foragerr.api.errors import error_body
from foragerr.metadata.sanitize import sanitize_cv_text

logger = logging.getLogger("foragerr.api.limits")

__all__ = ["RequestLimitsMiddleware", "install_request_limits", "sanitize_log_field"]

#: Upper bound on distinct peer addresses tracked by the rate limiter. The
#: single-user tailnet means one or two real peers; the LRU cap guarantees the
#: limiter's own memory can never grow unboundedly under a spoofed-source flood.
_MAX_RATE_CLIENTS = 1024

#: Bound on a single sanitized request field written to a log line.
_LOG_FIELD_MAX = 200


class _RequestBodyTooLarge(Exception):
    """Raised by the wrapped receive when the streamed body passes the cap."""


def sanitize_log_field(value: str, *, max_len: int = _LOG_FIELD_MAX) -> str:
    """Reduce an untrusted request string to a bounded, single-line log field.

    Routes the value through the FRG-NFR-012 control-character/ANSI sanitizer
    (:func:`foragerr.metadata.sanitize.sanitize_cv_text`) so CR/LF and escape
    sequences are stripped — a newline-bearing path or query can never forge a
    second log line — then truncates to ``max_len``.
    """
    cleaned = sanitize_cv_text(value) or ""
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    return cleaned


def _content_length(scope: Scope) -> int | None:
    """The parsed ``Content-Length`` header, or ``None`` if absent/unparseable."""
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _header_bytes(scope: Scope) -> int:
    """Total inbound header size in bytes (``name: value`` plus ``: `` + CRLF)."""
    return sum(len(name) + len(value) + 4 for name, value in scope.get("headers", []))


class _SlidingWindowRateLimiter:
    """A per-client sliding-window request counter with a bounded client table.

    Single-event-loop-thread by design (consistent with the rest of the ASGI
    stack): the check-then-mutate sequence contains no ``await``, so no lock is
    needed. The client table is an LRU-capped :class:`OrderedDict`, so a flood
    of distinct (possibly spoofed) source addresses can never grow it beyond
    ``max_clients`` entries.
    """

    def __init__(self, max_requests: int, window_seconds: float, *, max_clients: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = float(window_seconds)
        self.max_clients = max_clients
        self._clients: OrderedDict[str, deque[float]] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return self.max_requests > 0

    @property
    def tracked_clients(self) -> int:
        return len(self._clients)

    def check(self, key: str, now: float) -> tuple[bool, float]:
        """Record a request from ``key`` at monotonic time ``now``.

        Returns ``(allowed, retry_after_seconds)``. When disabled
        (``max_requests <= 0``) every request is allowed.
        """
        if not self.enabled:
            return True, 0.0
        stamps = self._clients.get(key)
        if stamps is None:
            stamps = deque()
            self._clients[key] = stamps
        cutoff = now - self.window_seconds
        while stamps and stamps[0] <= cutoff:
            stamps.popleft()
        self._clients.move_to_end(key)
        self._evict()
        if len(stamps) >= self.max_requests:
            retry_after = stamps[0] + self.window_seconds - now
            return False, max(retry_after, 0.0)
        stamps.append(now)
        return True, 0.0

    def _evict(self) -> None:
        while len(self._clients) > self.max_clients:
            self._clients.popitem(last=False)


class RequestLimitsMiddleware:
    """Pure-ASGI listener middleware enforcing the FRG-NFR-014 HTTP limits."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int,
        max_header_bytes: int,
        request_timeout_seconds: float,
        rate_max_requests: int,
        rate_window_seconds: float,
        max_rate_clients: int = _MAX_RATE_CLIENTS,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.max_header_bytes = max_header_bytes
        self.request_timeout = float(request_timeout_seconds)
        self._rate = _SlidingWindowRateLimiter(
            rate_max_requests, rate_window_seconds, max_clients=max_rate_clients
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # HTTP scope only: websocket + lifespan pass through untouched, so the
        # body cap and request timeout can never reach the long-lived WebSocket.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if _header_bytes(scope) > self.max_header_bytes:
            await self._reject(send, 431, "request header fields too large", scope)
            return

        client = scope.get("client")
        key = client[0] if client else "-"
        allowed, retry_after = self._rate.check(key, asyncio.get_running_loop().time())
        if not allowed:
            headers = [(b"retry-after", str(max(1, math.ceil(retry_after))).encode())]
            await self._reject(send, 429, "too many requests", scope, extra_headers=headers)
            return

        content_length = _content_length(scope)
        if content_length is not None and content_length > self.max_body_bytes:
            await self._reject(send, 413, "request body too large", scope)
            return

        await self._run(scope, receive, send)

    async def _run(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Run the downstream app under the streaming body cap and the
        time-to-first-byte request timeout."""
        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                started_event.set()
            await send(message)

        started_event = asyncio.Event()
        wrapped_receive = self._body_capped_receive(receive)
        app_task = asyncio.ensure_future(self.app(scope, wrapped_receive, send_wrapper))

        try:
            if self.request_timeout and self.request_timeout > 0:
                # Bound only time-to-first-response-byte: race the handler
                # against the moment it starts responding, with the timeout.
                start_waiter = asyncio.ensure_future(started_event.wait())
                try:
                    done, _pending = await asyncio.wait(
                        {app_task, start_waiter},
                        timeout=self.request_timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    start_waiter.cancel()
                if not done:
                    # Timed out before the handler produced any response.
                    await self._cancel(app_task)
                    if not started:
                        await self._reject(send, 503, "request timed out", scope)
                    return
            # The response has started (streaming continues unbounded) or the
            # handler finished; await it to completion / re-raise its result.
            await app_task
        except _RequestBodyTooLarge:
            await self._cancel(app_task)
            if not started:
                await self._reject(send, 413, "request body too large", scope)

    def _body_capped_receive(self, receive: Receive) -> Receive:
        """Wrap ``receive`` so the cumulative streamed body is aborted at the
        cap — no whole-body buffer ever accrues, even for a chunked / absent /
        lying ``Content-Length`` that drips unboundedly."""
        total = 0
        cap = self.max_body_bytes

        async def wrapped() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                if body:
                    total += len(body)
                    if total > cap:
                        raise _RequestBodyTooLarge()
            return message

        return wrapped

    @staticmethod
    async def _cancel(task: "asyncio.Future[None]") -> None:
        """Cancel ``task`` and absorb the cancellation / any stored error so a
        timed-out or aborted handler releases its worker cleanly."""
        if task.done():
            # Drain a stored exception so it is not reported as never-retrieved;
            # a genuine error surfacing here was already handled by the caller.
            task.exception()
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    async def _reject(
        self,
        send: Send,
        status: int,
        message: str,
        scope: Scope,
        *,
        extra_headers: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        """Send a bounded uniform-shape 4xx/5xx response and log the refusal
        with sanitized request fields."""
        self._log_refusal(status, message, scope)
        body = json.dumps(error_body(message)).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
        if extra_headers:
            headers.extend(extra_headers)
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    def _log_refusal(self, status: int, message: str, scope: Scope) -> None:
        """Warn about a refused request, sanitizing every request-sourced field
        (method/path/query) so a CR/LF-bearing request cannot forge a log line."""
        query = scope.get("query_string", b"")
        logger.warning(
            "listener refused request: status=%s reason=%s method=%s path=%s query=%s",
            status,
            message,
            sanitize_log_field(scope.get("method", "")),
            sanitize_log_field(scope.get("path", "")),
            sanitize_log_field(query.decode("latin-1", "replace")),
        )


def install_request_limits(app) -> None:
    """Install :class:`RequestLimitsMiddleware` on ``app`` from its settings.

    Called from :func:`foragerr.api.register_api`; reads the effective
    :class:`foragerr.config.Settings` off ``app.state.settings`` (populated by
    the app factory before the API area registers).
    """
    settings = app.state.settings
    app.add_middleware(
        RequestLimitsMiddleware,
        max_body_bytes=settings.listener_max_body_bytes,
        max_header_bytes=settings.listener_max_header_bytes,
        request_timeout_seconds=settings.listener_request_timeout_seconds,
        rate_max_requests=settings.listener_rate_max_requests,
        rate_window_seconds=settings.listener_rate_window_seconds,
    )
