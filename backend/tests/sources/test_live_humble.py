"""Env-gated live Humble smoke test (task 2.2b, FRG-SRC-002/003).

Skipped unless ``FORAGERR_TEST_HUMBLE_COOKIE`` is set (operator-provided, in the
repo-root ``.env``). Performs ONE real order-list call and ONE order-detail
round-trip against the operator's real account, asserting the schema fields the
client relies on still exist. It NEVER prints or logs the cookie, gamekeys, or
any signed URL. A network/auth failure (e.g. the sandbox cannot reach Humble, or
the session was invalidated) skips cleanly rather than failing the suite.

Redaction discipline: this test asserts only field *presence/shape*, never
echoes response values. If responses are ever captured to refresh the committed
fixtures, gamekeys / signature+expiry URL params / account email MUST be redacted
BEFORE anything is written under version control, and raw captures live only in a
gitignored scratchpad — never the repo.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from foragerr.http import HttpClientFactory
from foragerr.sources.humble import HumbleClient, HumbleError
from http_support import make_settings

COOKIE_ENV = "FORAGERR_TEST_HUMBLE_COOKIE"


def _load_cookie() -> str | None:
    if os.environ.get(COOKIE_ENV):
        return os.environ[COOKIE_ENV]
    for parent in Path(__file__).resolve().parents:
        env_file = parent / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(f"{COOKIE_ENV}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


@pytest.mark.req("FRG-SRC-002")
@pytest.mark.skipif(
    _load_cookie() is None,
    reason=f"live Humble smoke test disabled (set {COOKIE_ENV})",
)
async def test_live_order_list_and_detail(tmp_path):
    cookie = _load_cookie()
    assert cookie  # guarded by skipif; never printed
    settings = make_settings(tmp_path, source_min_request_interval_seconds=2.0)
    factory = HttpClientFactory(settings)  # real DNS + real network
    async with HumbleClient(factory, cookie, source_id=0, min_interval=2.0) as client:
        try:
            gamekeys = await client.list_gamekeys()
        except HumbleError as exc:  # network/auth — skip, never leak the cause value
            pytest.skip(f"live Humble call unavailable: {type(exc).__name__}")

        if not gamekeys:
            pytest.skip("live Humble account returned no orders")

        # One order-detail round-trip — assert the schema fields the client uses.
        entitlements = await client.fetch_order(gamekeys[0])
        for ent in entitlements:
            assert isinstance(ent.machine_name, str) and ent.machine_name
            assert isinstance(ent.human_name, str)
            assert ent.classification in ("comic", "other")
            for opt in ent.options:
                assert isinstance(opt.format, str)
                assert opt.md5 is None or len(opt.md5) == 32
