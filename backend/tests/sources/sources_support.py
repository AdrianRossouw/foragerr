"""Shared helpers for the store-source (Humble) test package.

No test performs real DNS or network I/O: the shared outbound factory is built
with a stub resolver (mapping the Humble host to a policy-acceptable public IP)
and an injected ``httpx.MockTransport`` serving the committed fixtures.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from foragerr.http import HttpClientFactory
from foragerr.sources.humble import HUMBLE_API_BASE
from http_support import PUBLIC_V4, StubResolver, make_settings

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: The Humble API host every request targets.
HUMBLE_HOST = httpx.URL(HUMBLE_API_BASE).host


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def make_factory(
    config_dir: Path,
    transport: httpx.AsyncBaseTransport,
    *,
    addr: str = PUBLIC_V4,
) -> HttpClientFactory:
    """A factory whose stub resolver maps the Humble host to ``addr`` and whose
    transport is the supplied stub — no real DNS or I/O."""
    settings = make_settings(config_dir)
    resolver = StubResolver({HUMBLE_HOST: [addr]})
    return HttpClientFactory(settings, resolver=resolver, transport=transport)


def json_response(status: int, body: bytes) -> httpx.Response:
    return httpx.Response(status, content=body, headers={"content-type": "application/json"})


def order_handler(
    *,
    list_body: bytes | None = None,
    order_bodies: dict[str, bytes] | None = None,
    list_status: int = 200,
    order_status: int = 200,
):
    """A MockTransport handler routing the two Humble endpoints to fixtures.

    ``order_bodies`` maps a gamekey to its order-detail body. A gamekey missing
    from the map falls back to the single ``default`` body if present.
    """
    order_bodies = order_bodies or {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/user/order":
            return json_response(list_status, list_body or b"[]")
        if path.startswith("/api/v1/order/"):
            gamekey = path.rsplit("/", 1)[-1]
            body = order_bodies.get(gamekey) or order_bodies.get("default") or b"{}"
            return json_response(order_status, body)
        return json_response(404, b"{}")

    return handler
