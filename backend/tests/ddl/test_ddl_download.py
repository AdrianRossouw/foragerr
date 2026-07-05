"""Download execution: streaming, size accounting, safe resume, outbound
security (FRG-DDL-008/009/012)."""

from __future__ import annotations

import httpx
import pytest

from foragerr.ddl.download import (
    CHUNK_SIZE,
    build_allowlist,
    download_link,
    partial_path_for,
)
from foragerr.ddl.errors import DdlDownloadError, OutboundNotAllowedError
from ddl_support import (
    make_cbz,
    make_factory,
    redirect,
    resp_full,
    resp_missing_cl,
    resp_range,
    resp_range_mismatch,
    resp_wrong_cl,
)

BASE = "https://getcomics.org"
DL_URL = "https://getcomics.org/dlds/run.php?id=1001"
ALLOW = build_allowlist(BASE)


def _staging(tmp_path):
    d = tmp_path / "ddl-staging"
    d.mkdir()
    return d


@pytest.mark.req("FRG-DDL-008")
def test_chunk_size_is_at_least_64_kib():
    assert CHUNK_SIZE >= 64 * 1024


@pytest.mark.req("FRG-DDL-008")
async def test_streams_full_body_into_partial_with_byte_accounting(tmp_path):
    body = make_cbz()
    factory, _ = make_factory(tmp_path, lambda req: resp_full(body))
    partial = partial_path_for(_staging(tmp_path), 7)
    outcome = await download_link(
        factory=factory, url=DL_URL, partial_path=partial, allowlist=ALLOW
    )
    assert outcome.bytes_received == len(body)
    assert partial.read_bytes() == body


@pytest.mark.req("FRG-DDL-008")
async def test_missing_content_length_fails_after_retry(tmp_path):
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return resp_missing_cl(make_cbz())

    factory, _ = make_factory(tmp_path, handler)
    partial = partial_path_for(_staging(tmp_path), 8)
    with pytest.raises(DdlDownloadError, match="Content-Length"):
        await download_link(
            factory=factory, url=DL_URL, partial_path=partial, allowlist=ALLOW
        )
    assert calls["n"] == 2  # one retry (re-fetch live), then fail


@pytest.mark.req("FRG-DDL-008")
async def test_size_mismatch_beyond_tolerance_fails(tmp_path):
    body = make_cbz()
    factory, _ = make_factory(
        tmp_path, lambda req: resp_wrong_cl(body, declared=len(body) + 500_000)
    )
    partial = partial_path_for(_staging(tmp_path), 9)
    with pytest.raises(DdlDownloadError, match="size mismatch"):
        await download_link(
            factory=factory, url=DL_URL, partial_path=partial, allowlist=ALLOW
        )


@pytest.mark.req("FRG-DDL-009")
async def test_valid_206_resume_appends_from_partial_offset(tmp_path):
    body = make_cbz()
    prefix = len(body) // 3
    partial = partial_path_for(_staging(tmp_path), 10)
    partial.write_bytes(body[:prefix])  # a pre-existing partial

    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["range"] = req.headers.get("range")
        assert seen["range"] == f"bytes={prefix}-"
        return resp_range(body, prefix)

    factory, _ = make_factory(tmp_path, handler)
    outcome = await download_link(
        factory=factory, url=DL_URL, partial_path=partial, allowlist=ALLOW
    )
    assert partial.read_bytes() == body  # appended, not duplicated
    assert outcome.bytes_received == len(body)


@pytest.mark.req("FRG-DDL-009")
async def test_200_full_body_forces_clean_restart_never_appends(tmp_path):
    body = make_cbz()
    prefix = len(body) // 3
    partial = partial_path_for(_staging(tmp_path), 11)
    partial.write_bytes(body[:prefix])
    # Server ignores Range and returns the whole body with 200.
    factory, _ = make_factory(tmp_path, lambda req: resp_full(body))
    outcome = await download_link(
        factory=factory, url=DL_URL, partial_path=partial, allowlist=ALLOW
    )
    assert partial.read_bytes() == body  # restarted from zero, not prefix+body
    assert outcome.bytes_received == len(body)


@pytest.mark.req("FRG-DDL-009")
async def test_content_range_offset_mismatch_forces_restart(tmp_path):
    body = make_cbz()
    prefix = len(body) // 3
    partial = partial_path_for(_staging(tmp_path), 12)
    partial.write_bytes(body[:prefix])
    # 206 but Content-Range claims a different offset than requested.
    factory, _ = make_factory(
        tmp_path, lambda req: resp_range_mismatch(body, requested=0, claimed=0)
    )
    outcome = await download_link(
        factory=factory, url=DL_URL, partial_path=partial, allowlist=ALLOW
    )
    assert partial.read_bytes() == body
    assert outcome.bytes_received == len(body)


@pytest.mark.req("FRG-DDL-012")
async def test_redirect_to_private_address_is_refused_ssrf(tmp_path):
    # A scraped link 302-redirecting to an internal address is refused by the
    # egress policy before any body is fetched, surfaced as a host failure.
    factory, _ = make_factory(
        tmp_path, lambda req: redirect("http://10.0.0.5/secret")
    )
    partial = partial_path_for(_staging(tmp_path), 13)
    with pytest.raises(DdlDownloadError):
        await download_link(
            factory=factory, url=DL_URL, partial_path=partial, allowlist=ALLOW
        )
    assert not partial.exists() or partial.read_bytes() == b""


@pytest.mark.req("FRG-DDL-012")
async def test_off_allowlist_redirect_hop_is_refused(tmp_path):
    factory, _ = make_factory(
        tmp_path, lambda req: redirect("https://evil.example/malware.cbz")
    )
    partial = partial_path_for(_staging(tmp_path), 14)
    with pytest.raises(OutboundNotAllowedError):
        await download_link(
            factory=factory, url=DL_URL, partial_path=partial, allowlist=ALLOW
        )


@pytest.mark.req("FRG-DDL-012")
async def test_initial_off_allowlist_url_never_fetched(tmp_path):
    factory, transport = make_factory(tmp_path, lambda req: resp_full(make_cbz()))
    partial = partial_path_for(_staging(tmp_path), 15)
    with pytest.raises(OutboundNotAllowedError):
        await download_link(
            factory=factory,
            url="https://evil.example/x.cbz",
            partial_path=partial,
            allowlist=ALLOW,
        )
    assert transport.requests == []  # refused before any connection
