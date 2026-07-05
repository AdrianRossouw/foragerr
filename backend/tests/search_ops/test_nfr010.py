"""End-to-end resilience to a misbehaving indexer (FRG-NFR-010).

Drives a real search over the ``external`` HTTP profile against genuine sockets:
a hostile fixture server (hangs / drips / junk / 429-storm) alongside a healthy
one. The bounded connect/read timeouts and byte cap plus the per-provider
back-off ladder must keep the hostile provider from wedging the search — the
healthy indexer in the same command completes and returns its release, and the
hostile provider's failure is recorded.
"""

from __future__ import annotations

import asyncio

import pytest

from foragerr.http import HttpClientFactory
from foragerr.indexers.caps import CapsCache
from foragerr.providers.backoff import PROVIDER_INDEXER, ProviderBackoff
from foragerr.search_ops import run_search
from http_support import fixture_server, make_settings
from indexers_support import caps_doc, feed_item, newznab_feed
from .support import make_indexer, make_issue, make_series


def _http(body: bytes, *, status: str = "200 OK", extra: bytes = b"") -> bytes:
    return (
        f"HTTP/1.1 {status}\r\n".encode()
        + b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        + extra
        + b"Connection: close\r\n\r\n"
        + body
    )


async def _read_path(reader: asyncio.StreamReader) -> str:
    raw = await reader.readuntil(b"\r\n\r\n")
    return raw.split(b" ", 2)[1].decode()


def _healthy_handler():
    async def handler(reader, writer):
        path = await _read_path(reader)
        body = caps_doc() if "t=caps" in path else newznab_feed(
            feed_item(guid="healthy-1", title="Saga 007 (2012)")
        )
        writer.write(_http(body))
        await writer.drain()

    return handler


def _hang_handler():
    async def handler(reader, writer):
        await _read_path(reader)
        await reader.read()  # accept then hang forever — must be timeout-bounded
    return handler


def _junk_and_429_handler():
    async def handler(reader, writer):
        path = await _read_path(reader)
        if "t=caps" in path:
            writer.write(_http(b"this is not xml at all <<< &&&"))  # junk
        else:
            writer.write(_http(b"", status="429 Too Many Requests",
                               extra=b"Retry-After: 1\r\n"))  # 429 storm
        await writer.drain()
    return handler


def _factory(tmp_path) -> HttpClientFactory:
    settings = make_settings(
        tmp_path,
        http_connect_timeout_seconds=1.0,
        http_read_timeout_seconds=0.5,
        http_write_timeout_seconds=1.0,
        http_pool_timeout_seconds=1.0,
        http_max_response_bytes=4096,
    )
    return HttpClientFactory(settings, test_allow_addresses={"127.0.0.1"})


async def _search_two(db, tmp_path, hostile_handler, *, series_id, issue_id):
    """Search a hostile + a healthy indexer in one command; return the result."""
    async with fixture_server(hostile_handler) as hostile_base, fixture_server(
        _healthy_handler()
    ) as healthy_base:
        # Hostile FIRST: if it wedged the loop, the healthy one would never run.
        await make_indexer(db, name="Hostile", base_url=hostile_base, priority=5)
        await make_indexer(db, name="Healthy", base_url=healthy_base, priority=10)
        return await run_search(
            db=db,
            settings=make_settings(tmp_path),
            factory=_factory(tmp_path),
            backoff=ProviderBackoff(db),
            caps_cache=CapsCache(),
            series_id=series_id,
            issue_id=issue_id,
            path="auto",
            min_interval=0.0,
        )


@pytest.mark.req("FRG-NFR-010")
async def test_hanging_indexer_is_bounded_and_healthy_completes(
    db, format_profile_id, root_folder_id
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")

    result = await asyncio.wait_for(
        _search_two(
            db, db.db_path.parent, _hang_handler(),
            series_id=series_id, issue_id=issue_id,
        ),
        timeout=15.0,  # the whole command must finish well inside this
    )
    assert result is not None
    # The healthy indexer returned and its release was approved.
    assert result.approved
    assert result.approved[0].candidate.indexer_name == "Healthy"
    # The hostile indexer's search failed and is recorded (not silently lost).
    hostile = next(o for o in result.indexer_outcomes if o.indexer_name == "Hostile")
    assert hostile.failure is not None
    assert not hostile.candidates


@pytest.mark.req("FRG-NFR-010")
async def test_junk_and_429_indexer_isolated_healthy_completes(
    db, format_profile_id, root_folder_id
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")

    result = await asyncio.wait_for(
        _search_two(
            db, db.db_path.parent, _junk_and_429_handler(),
            series_id=series_id, issue_id=issue_id,
        ),
        timeout=15.0,
    )
    assert result is not None
    assert result.approved
    assert result.approved[0].candidate.indexer_name == "Healthy"

    # The 429 storm drove the hostile provider onto the back-off ladder.
    hostile = next(o for o in result.indexer_outcomes if o.indexer_name == "Hostile")
    assert hostile.failure is not None
    indexer_ids = {o.indexer_id for o in result.indexer_outcomes if o.indexer_name == "Hostile"}
    backoff = ProviderBackoff(db)
    assert await backoff.is_backing_off(PROVIDER_INDEXER, indexer_ids.pop())
