"""Shared helpers for the store-source (Humble) test package.

No test performs real DNS or network I/O: the shared outbound factory is built
with a stub resolver (mapping the Humble host to a policy-acceptable public IP)
and an injected ``httpx.MockTransport`` serving the committed fixtures.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from foragerr.http import HttpClientFactory
from foragerr.library import repo as library_repo
from foragerr.sources import repo
from foragerr.sources.humble import HUMBLE_API_BASE
from foragerr.sources.models import SourceEntitlementRow
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.service import run_sync
from foragerr.sources.settings import HumbleSettings
from http_support import PUBLIC_V4, StubResolver, make_settings

#: The synthetic Humble order gamekey every synced-source fixture serves.
GAMEKEY = "aBcD1234synthetic"


@pytest.fixture
async def format_profile_id(db) -> int:
    """The seeded default format profile id (imported as a fixture by the
    review/reconcile tests; kept here rather than a tests/sources conftest.py,
    which would shadow the top-level ``conftest`` module for bare-import tests)."""
    from sqlalchemy import select

    from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

    async with db.read_session() as session:
        return (
            await session.execute(
                select(FormatProfileRow.id).where(
                    FormatProfileRow.name == DEFAULT_PROFILE_NAME
                )
            )
        ).scalar_one()


@pytest.fixture
async def root_folder_id(db, tmp_path: Path) -> int:
    """A real root folder for building library series in the sources tests."""
    from foragerr.library import repo as library_repo

    root = tmp_path / "library-root"
    root.mkdir()
    async with db.write_session() as session:
        row = await library_repo.create_root_folder(session, str(root))
        return row.id

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


class FakeCommands:
    """Records enqueued commands (the grab / refresh hand-offs) without a real
    queue."""

    def __init__(self):
        self.enqueued: list[tuple] = []

    async def enqueue(self, name, payload=None, *, triggered_by="manual"):
        self.enqueued.append((name, payload, triggered_by))
        return SimpleNamespace(id=len(self.enqueued), status="queued")

    def grabs(self) -> list[tuple]:
        return [c for c in self.enqueued if c[0] == "source-grab"]


async def _synced_source(
    db,
    config_dir: Path,
    *,
    auto_sync: bool = False,
    connection_state: str | None = None,
):
    """Create + sync a Humble source against the shared ``order_comics.json``
    fixture. ``connection_state`` is passed through to ``repo.create_source``
    only when given — omitted (the default) leaves the repo's own default in
    place, matching callers that never cared about connection state."""
    kwargs: dict = {
        "source_type": TYPE_HUMBLE,
        "name": "Humble Bundle",
        "settings": HumbleSettings(session_cookie="SYNTH-COOKIE"),
        "auto_sync": auto_sync,
    }
    if connection_state is not None:
        kwargs["connection_state"] = connection_state
    source = await repo.create_source(db, **kwargs)
    handler = order_handler(
        list_body=b'[{"gamekey":"%s"}]' % GAMEKEY.encode(),
        order_bodies={GAMEKEY: fixture_bytes("order_comics.json")},
    )
    factory = make_factory(config_dir, httpx.MockTransport(handler))
    await run_sync(db, factory, source, min_interval=0.0)
    return source


async def _comic(db, source_id, machine_name) -> SourceEntitlementRow:
    for e in await repo.list_entitlements(db, source_id, classification="comic"):
        if e.machine_name == machine_name:
            return e
    raise AssertionError(f"no entitlement {machine_name}")


async def _mk_series(db, root_folder_id, format_profile_id, *, cvid, title):
    async with db.write_session() as session:
        series = await library_repo.create_series(
            session,
            cv_volume_id=cvid,
            title=title,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=f"/tmp/comics/{title} ({cvid})",
        )
        return series.id
