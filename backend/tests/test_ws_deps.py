"""The shipped server must actually be able to speak WebSocket (FRG-API-010).

The FastAPI TestClient exercises ``/api/v1/ws`` through an in-process ASGI
bridge, so the whole suite stays green even if uvicorn — the real server in
the Docker image — has no WebSocket protocol implementation installed (plain
``uvicorn`` depends only on ``click`` and ``h11``; the upgrade handshake then
fails at runtime). Found by the change-7 gate review. ``websockets`` is a
declared direct dependency precisely so uvicorn's auto-protocol resolves.
"""

import pytest


@pytest.mark.req("FRG-API-010")
def test_uvicorn_resolves_a_websocket_protocol():
    from uvicorn.protocols.websockets.auto import AutoWebSocketsProtocol

    assert AutoWebSocketsProtocol is not None, (
        "uvicorn found no websockets/wsproto backend — the /api/v1/ws "
        "endpoint would fail its upgrade in the shipped container"
    )


@pytest.mark.req("FRG-API-010")
def test_websockets_is_importable():
    import websockets  # noqa: F401 — the declared direct dependency