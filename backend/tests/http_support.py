"""Shared fixtures/helpers for the outbound-HTTP factory tests.

Provides settings construction, a stub DNS resolver (no test ever performs a
real DNS lookup or external connection), transports that record or forbid
connections, and a minimal raw-HTTP fixture server bound to 127.0.0.1 for the
live timeout/byte-cap/redirect scenarios.
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Mapping, Sequence

import httpx

from foragerr.config import Settings

PUBLIC_V4 = "203.0.113.10"  # TEST-NET-3 — policy-acceptable, never connected to


def make_settings(config_dir: Path, **overrides: object) -> Settings:
    """A Settings instance rooted in a temp dir (env is stripped by the
    autouse conftest fixture, so kwargs win)."""
    return Settings(config_dir=config_dir, **overrides)


class StubResolver:
    """Injectable resolver: a fixed name->addresses table, recorded calls,
    OSError for unknown names (so no test can fall through to real DNS)."""

    def __init__(self, table: Mapping[str, Sequence[str]] | None = None) -> None:
        self.table = dict(table or {})
        self.calls: list[str] = []

    async def __call__(self, host: str) -> Sequence[str]:
        self.calls.append(host)
        try:
            return self.table[host]
        except KeyError:
            raise OSError(f"stub resolver: unknown host {host!r}") from None


class NoConnectTransport(httpx.AsyncBaseTransport):
    """Fails the test if any connection is ever attempted."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"outbound connection attempted to {request.url}")


class RecordingTransport(httpx.AsyncBaseTransport):
    """Runs a handler and records every request that reached the transport."""

    def __init__(
        self, handler: Callable[[httpx.Request], httpx.Response]
    ) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)


HandlerFn = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]


@asynccontextmanager
async def fixture_server(handler: HandlerFn) -> AsyncIterator[str]:
    """A raw asyncio TCP server on 127.0.0.1; yields its base URL."""
    tasks: set[asyncio.Task] = set()

    async def on_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            tasks.add(task)
        try:
            await handler(reader, writer)
        except (
            ConnectionResetError,
            BrokenPipeError,
            asyncio.IncompleteReadError,
            asyncio.CancelledError,
        ):
            pass
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    server = await asyncio.start_server(on_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.close()
        for task in tasks:
            task.cancel()
        with contextlib.suppress(Exception):
            await server.wait_closed()


def http_fixture_handler(request_log: list[str]) -> HandlerFn:
    """One handler covering all live fixture behaviors, keyed by path:

    - ``/ok``          -> small 200 response
    - ``/hang``        -> accepts the request, never sends anything
    - ``/drip``        -> 200 with no Content-Length, drips bytes forever
    - ``/big-declared``-> 200 declaring a huge Content-Length
    - ``/r/<n>``       -> 302 chain counting down to a 200 at ``/r/0``
    """

    async def handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        raw = await reader.readuntil(b"\r\n\r\n")
        path = raw.split(b" ", 2)[1].decode()
        request_log.append(path)

        if path == "/hang":
            await reader.read()  # hold until the client gives up/disconnects
            return
        if path == "/drip":
            writer.write(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n")
            await writer.drain()
            while True:  # close-delimited body, dripped without end
                writer.write(b"x" * 1024)
                await writer.drain()
                await asyncio.sleep(0.005)
        if path == "/big-declared":
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: 999999999\r\n"
                b"Connection: close\r\n\r\n"
            )
            await writer.drain()
            writer.write(b"y" * 1024)
            await writer.drain()
            return
        if path.startswith("/r/"):
            hops_left = int(path[3:])
            if hops_left > 0:
                writer.write(
                    f"HTTP/1.1 302 Found\r\nLocation: /r/{hops_left - 1}\r\n"
                    "Content-Length: 0\r\nConnection: close\r\n\r\n".encode()
                )
            else:
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
                    b"Connection: close\r\n\r\nok"
                )
            await writer.drain()
            return
        body = b"hello"
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + body
        )
        await writer.drain()

    return handler
