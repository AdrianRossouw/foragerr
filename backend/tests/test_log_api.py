"""FRG-API-021 / FRG-NFR-015 — GET /api/v1/log and the ring-buffer log
capture that backs it.

The endpoint tests mount ONLY the log router over a fresh
:func:`foragerr.logging_buffer.install_log_buffer` handler (not the full
``create_app``/DB/scheduler stack): this exercises the real production
install path — the same function ``app.py`` calls at startup — while
keeping each test's buffer size and contents fully isolated and fast. The
shared ``_isolate`` autouse fixture (conftest.py) sweeps any handler marked
``_foragerr`` after every test, so buffers never leak between tests.
"""

from __future__ import annotations

import contextlib
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from foragerr.api.errors import register_error_handlers
from foragerr.api.log import router as log_router
from foragerr.config import ConfigError, load_settings
from foragerr.logging import MASK, register_secret
from foragerr.logging_buffer import install_log_buffer

SENTINEL = "sekrit-log-viewer-9f3a7c21"


#: Common ancestor for every logger these tests emit through. Its level is
#: raised to DEBUG for the duration of ``_log_app`` (below) so INFO-level
#: test records actually reach the handler — scoped to THIS subtree only
#: (not the root logger), so unrelated noise a real process also logs
#: (httpx's own request-logging, asyncio) stays exactly as filtered as it
#: would be in production and never pollutes the "empty buffer" / overflow
#: assertions.
_TEST_LOGGER_NAME = "foragerr.test"


@contextlib.contextmanager
def _log_app(maxlen: int):
    """A minimal FastAPI app exposing only ``GET /api/v1/log``, backed by a
    real ring-buffer handler installed on the root logger the same way
    ``create_app`` does."""
    test_logger = logging.getLogger(_TEST_LOGGER_NAME)
    previous_level = test_logger.level
    test_logger.setLevel(logging.DEBUG)
    handler = install_log_buffer(maxlen)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(log_router, prefix="/api/v1")
    app.state.log_buffer = handler
    try:
        with TestClient(app) as client:
            yield client
    finally:
        test_logger.setLevel(previous_level)


@pytest.fixture
def log_client():
    with _log_app(2000) as client:
        yield client


# --------------------------------------------------------------------------
# FRG-API-021
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-API-021")
def test_log_paged_newest_first_with_level_and_logger_filters(log_client):
    logging.getLogger("foragerr.test.search").info("info one")
    logging.getLogger("foragerr.test.search").warning("warn one")
    logging.getLogger("foragerr.test.other").error("err one")
    logging.getLogger("foragerr.test.search.deep").error("err two")

    resp = log_client.get("/api/v1/log?level=WARNING&logger=foragerr.test.search")
    assert resp.status_code == 200
    body = resp.json()
    assert body["page"] == 1
    assert body["pageSize"] == 50
    assert body["sortKey"] == "time"
    assert body["sortDirection"] == "desc"
    assert body["totalRecords"] == 2
    # WARNING+ only, logger prefix match only: excludes "info one" (below
    # WARNING) and "err one" (different logger), newest first.
    assert [r["message"] for r in body["records"]] == ["err two", "warn one"]
    assert all(r["logger"].startswith("foragerr.test.search") for r in body["records"])
    assert all(r["level"] in ("WARNING", "ERROR") for r in body["records"])

    # Paging metadata is consistent with the FILTERED total, and pages are
    # stable slices of that filtered, newest-first ordering.
    page1 = log_client.get(
        "/api/v1/log?level=WARNING&logger=foragerr.test.search&page=1&pageSize=1"
    ).json()
    page2 = log_client.get(
        "/api/v1/log?level=WARNING&logger=foragerr.test.search&page=2&pageSize=1"
    ).json()
    assert page1["totalRecords"] == page2["totalRecords"] == 2
    assert page1["records"][0]["message"] == "err two"
    assert page2["records"][0]["message"] == "warn one"


@pytest.mark.req("FRG-API-021")
def test_log_rejects_unknown_level_filter(log_client):
    resp = log_client.get("/api/v1/log?level=NOPE")
    assert resp.status_code == 400
    body = resp.json()
    assert body["errors"][0]["field"] == "level"


@pytest.mark.req("FRG-API-021")
def test_registered_secret_never_served_by_log_api(log_client):
    register_secret(SENTINEL)
    logging.getLogger("foragerr.test.secret").error(
        "upstream call used key " + SENTINEL
    )

    resp = log_client.get("/api/v1/log")
    assert resp.status_code == 200
    # The raw secret must appear NOWHERE in the response body.
    assert SENTINEL not in resp.text

    record = next(
        r for r in resp.json()["records"] if r["logger"] == "foragerr.test.secret"
    )
    assert MASK in record["message"]
    assert SENTINEL not in record["message"]


@pytest.mark.req("FRG-API-021")
def test_empty_buffer_after_restart_returns_empty_page(log_client):
    # Scoped to our own logger namespace via the `logger` prefix filter: the
    # full test session shares one process-wide root logger, so an earlier
    # test elsewhere may have left ambient library noise (httpx's own
    # request logging, asyncio) flowing into a freshly-installed buffer at
    # whatever level that earlier test left the root logger at. Filtering to
    # `foragerr.test.fresh` keeps the assertion about OUR buffer's
    # empty-then-populated behavior deterministic regardless of that
    # environmental state — it does not weaken what's under test, since the
    # underlying deque genuinely starts empty for this fixture either way.
    resp = log_client.get("/api/v1/log?logger=foragerr.test.fresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totalRecords"] == 0
    assert body["records"] == []

    logging.getLogger("foragerr.test.fresh").info("first record after restart")

    resp2 = log_client.get("/api/v1/log?logger=foragerr.test.fresh")
    body2 = resp2.json()
    assert body2["totalRecords"] == 1
    assert body2["records"][0]["message"] == "first record after restart"


# --------------------------------------------------------------------------
# FRG-NFR-015
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-NFR-015")
def test_buffer_never_exceeds_configured_bound():
    cap = 5
    total_emitted = cap + 7
    with _log_app(cap) as client:
        log = logging.getLogger("foragerr.test.overflow")
        for i in range(total_emitted):
            log.info("record %03d", i)

        body = client.get(f"/api/v1/log?pageSize={cap + 10}").json()
        assert body["totalRecords"] == cap  # never exceeds the configured cap

        kept_oldest_first = range(total_emitted - cap, total_emitted)
        expected_newest_first = [f"record {i:03d}" for i in reversed(kept_oldest_first)]
        assert [r["message"] for r in body["records"]] == expected_newest_first


@pytest.mark.req("FRG-NFR-015")
@pytest.mark.parametrize("value", ["0", "-3", "not-a-number"])
def test_invalid_log_buffer_records_fails_fast(config_dir, monkeypatch, value):
    monkeypatch.setenv("FORAGERR_LOG_BUFFER_RECORDS", value)
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    assert "log_buffer_records" in str(excinfo.value)
