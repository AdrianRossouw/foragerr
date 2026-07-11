"""The hardened external pull-source fetch client (FRG-PULL-002).

Every delta scenario of FRG-PULL-002 is exercised here: a happy parse of source
JSON into typed entries; the egress profile refusing a loopback source URL and
the request never touching the transport; oversized/malformed bodies degrading
without raising; per-entry field abuse (huge strings, CR/LF/ANSI injection, bad
dates) bounded or skipped; the entry-count cap; proof the fetch flows through the
shared factory (no direct httpx); the documented 619/522/666 error-code mapping;
and the degraded-source health/back-off behaviour on an outage.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from foragerr.health.service import HealthService
from foragerr.http import HttpClientFactory
from foragerr.providers.backoff import (
    FAST_FORWARD_MIN_LEVEL,
    PROVIDER_PULL,
    PULL_PROVIDER_ID,
    ProviderBackoff,
)
from foragerr.pull.source import (
    MAX_FIELD_LENGTH,
    PullBadDate,
    PullSourceClient,
    PullSourceOutage,
    parse_pull_payload,
)
from http_support import (  # noqa: F401 - shared HTTP test helpers
    PUBLIC_V4,
    NoConnectTransport,
    RecordingTransport,
    StubResolver,
    make_settings,
)

SOURCE_HOST = "walksoftly.example"
SOURCE_URL = f"https://{SOURCE_HOST}/newcomics.php"


def _factory(
    tmp_path: Path,
    transport: httpx.AsyncBaseTransport,
    *,
    addr: str = PUBLIC_V4,
    allow: tuple[str, ...] = (),
) -> HttpClientFactory:
    """A factory whose stub resolver maps the source host to ``addr`` and whose
    transport is the supplied stub — no test ever performs real DNS or I/O."""
    settings = make_settings(tmp_path)
    resolver = StubResolver({SOURCE_HOST: [addr]})
    return HttpClientFactory(
        settings, resolver=resolver, transport=transport, test_allow_addresses=allow
    )


def _mock(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _sample_entries() -> list[dict]:
    return [
        {
            "series": "Saga",
            "issue": "#60",
            "publisher": "Image Comics",
            "shipdate": "2026-07-08",
            "comicid": 18166,  # int id
            "issueid": "900001",  # string id — coerced
        },
        {
            "series": "Immortal Hulk",
            "issue": "50",
            "publisher": None,  # nullable publisher
            "shipdate": "2026-07-08",
            "comicid": None,
            "issueid": None,
        },
    ]


# --- B.1 egress profile + happy parse ---------------------------------------


@pytest.mark.req("FRG-PULL-002")
async def test_happy_parse_maps_source_json_to_entries(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_sample_entries())

    client = PullSourceClient(_factory(tmp_path, _mock(handler)), SOURCE_URL)
    async with client:
        entries = await client.fetch_week(week=27, year=2026)

    assert len(entries) == 2
    saga = entries[0]
    assert saga.series_name == "Saga"
    assert saga.issue_number == "#60"  # raw token verbatim (normalized at match)
    assert saga.publisher == "Image Comics"
    assert saga.release_date.isoformat() == "2026-07-08"
    assert saga.cv_series_id == 18166
    assert saga.cv_issue_id == 900001  # string coerced to int
    hulk = entries[1]
    assert hulk.publisher is None
    assert hulk.cv_series_id is None and hulk.cv_issue_id is None


@pytest.mark.req("FRG-PULL-002")
async def test_request_flows_through_factory_over_external_profile(tmp_path):
    # A RecordingTransport captures the request the shared factory issued; the
    # module never imports httpx/requests itself (the shared static-guard test
    # enforces that globally — asserted here too for the delta).
    recorder = RecordingTransport(lambda r: httpx.Response(200, json=[]))
    client = PullSourceClient(_factory(tmp_path, recorder), SOURCE_URL)
    async with client:
        await client.fetch_week(week=27, year=2026)

    assert len(recorder.requests) == 1
    req = recorder.requests[0]
    assert req.url.host == SOURCE_HOST
    assert req.url.params["week"] == "27"
    assert req.url.params["year"] == "2026"
    assert req.headers["user-agent"].startswith("foragerr/")

    source_text = (
        Path(__file__).resolve().parents[2]
        / "src/foragerr/pull/source.py"
    ).read_text(encoding="utf-8")
    assert "import httpx" not in source_text
    assert "import requests" not in source_text


@pytest.mark.req("FRG-PULL-002")
async def test_loopback_source_url_refused_per_hop_not_fetched(tmp_path):
    # The source host resolves to loopback: the external egress profile must
    # refuse it BEFORE any connection — NoConnectTransport would raise if the
    # request ever reached the transport, and the refusal is a degraded outage.
    client = PullSourceClient(
        _factory(tmp_path, NoConnectTransport(), addr="127.0.0.1"),
        SOURCE_URL,
    )
    async with client:
        with pytest.raises(PullSourceOutage) as exc:
            await client.fetch_week(week=27, year=2026)
    assert exc.value.reason == "egress-refused"  # refused per-hop, not a transport fault


# --- B.2 untrusted JSON: oversized / malformed / field abuse / cap ----------


@pytest.mark.req("FRG-PULL-002")
async def test_oversized_body_is_refused_as_outage(tmp_path):
    big = b"[" + b'{"series":"x","issue":"1","shipdate":"2026-07-08"},' * 100 + b"]"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=big)

    client = PullSourceClient(
        _factory(tmp_path, _mock(handler)), SOURCE_URL, max_response_bytes=64
    )
    async with client:
        with pytest.raises(PullSourceOutage) as exc:
            await client.fetch_week(week=27, year=2026)
    assert exc.value.reason == "fetch-refused"


@pytest.mark.req("FRG-PULL-002")
async def test_malformed_body_degrades_without_raising_uncaught(tmp_path):
    for body in (b"{not json at all", b'{"not":"an array"}'):

        def handler(request: httpx.Request, _body=body) -> httpx.Response:
            return httpx.Response(200, content=_body)

        client = PullSourceClient(_factory(tmp_path, _mock(handler)), SOURCE_URL)
        async with client:
            with pytest.raises(PullSourceOutage) as exc:
                await client.fetch_week(week=27, year=2026)
        assert exc.value.reason == "malformed"


@pytest.mark.req("FRG-PULL-002")
def test_per_entry_field_abuse_is_bounded_and_sanitized():
    abusive = [
        # huge series name — must be length-capped
        {"series": "A" * (MAX_FIELD_LENGTH + 5000), "issue": "1", "shipdate": "2026-07-08"},
        # CR/LF + ANSI log-forging attempt — control chars stripped, one line
        {
            "series": "Evil\r\nINJECTED 2026-01-01 ERROR\x1b[31m hack",
            "issue": "#2\n",
            "shipdate": "2026-07-08",
        },
        # bad date — entry dropped entirely
        {"series": "Skip Me", "issue": "3", "shipdate": "not-a-date"},
        # missing required series — dropped
        {"issue": "4", "shipdate": "2026-07-08"},
        # hostile huge id — dropped to None (candidate only)
        {"series": "Big Id", "issue": "5", "shipdate": "2026-07-08", "comicid": 10**30},
    ]
    entries = parse_pull_payload(json.dumps(abusive).encode())

    # bad-date + missing-series rows are gone; three survive.
    assert len(entries) == 3
    huge, injected, big_id = entries

    assert len(huge.series_name) == MAX_FIELD_LENGTH  # truncated to the cap

    assert "\n" not in injected.series_name and "\r" not in injected.series_name
    assert "\x1b" not in injected.series_name  # ANSI stripped
    assert "\n" not in injected.issue_number  # control chars stripped from every field

    assert big_id.series_name == "Big Id"
    assert big_id.cv_series_id is None  # absurd id refused


@pytest.mark.req("FRG-NFR-012")
def test_bidi_and_zero_width_chars_are_stripped_from_source_fields():
    """Trojan-Source hardening at pull ingest (RISK-011/014, FRG-NFR-012): a
    hostile source string carrying RLO (‮) / zero-width / isolate / BOM format
    characters is stripped clean before storage, reusing the SAME character
    table ``metadata.sanitize`` applies to ComicVine text (no duplication)."""
    payload = [
        {
            # RLO (U+202E) + ZWSP (U+200B) buried inside the series name.
            "series": "Sa‮ga​",
            "issue": "1",
            # LRI isolate (U+2066) + BOM/ZWNBSP (U+FEFF) inside the publisher.
            "publisher": "Image⁦ Comics﻿",
            "shipdate": "2026-07-08",
        }
    ]
    entries = parse_pull_payload(json.dumps(payload).encode())

    assert len(entries) == 1
    entry = entries[0]
    # The bidi/zero-width characters are gone; the visible text survives intact.
    assert entry.series_name == "Saga"
    assert entry.publisher == "Image Comics"
    for ch in ("‮", "​", "⁦", "﻿"):
        assert ch not in entry.series_name
        assert ch not in (entry.publisher or "")


@pytest.mark.req("FRG-PULL-009")
async def test_522_on_only_the_future_week_is_a_skip_not_a_degrade(tmp_path, db):
    """FRG-PULL-009 Decision 7: a 522 outage on ONLY the future week is contained
    to a single-week skip — current + previous are still returned for storage,
    the run is NOT degraded, the future week lands in ``future_skipped``, and NO
    ladder failure is recorded (a flaky speculative week never backs off a source
    whose current/previous data is good)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["week"] == "29":  # the future week only
            return httpx.Response(522)
        return httpx.Response(200, json=_sample_entries())

    backoff = ProviderBackoff(db)
    client = PullSourceClient(
        _factory(tmp_path, _mock(handler)), SOURCE_URL, backoff=backoff
    )
    async with client:
        outcome = await client.fetch_weeks(
            [(28, 2026), (27, 2026), (29, 2026)], future_week=(29, 2026)
        )

    assert outcome.degraded is False
    assert outcome.outage_reason is None
    assert [w.week for w in outcome.weeks] == [28, 27]  # current + previous kept
    assert outcome.future_skipped == ((29, 2026),)
    # Good current/previous data → the run records success → source stays healthy.
    assert (await backoff.status(PROVIDER_PULL, PULL_PROVIDER_ID)).healthy


@pytest.mark.req("FRG-PULL-009")
@pytest.mark.req("FRG-PULL-002")
async def test_522_on_current_week_still_degrades_even_with_future_week_set(
    tmp_path, db
):
    """The future-week containment must not weaken FRG-PULL-002: a 522 on the
    current (or previous) week degrades the whole run exactly as before, even
    when a ``future_week`` is declared."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(522)  # current week (fetched first) is down

    backoff = ProviderBackoff(db)
    client = PullSourceClient(
        _factory(tmp_path, _mock(handler)), SOURCE_URL, backoff=backoff
    )
    async with client:
        outcome = await client.fetch_weeks(
            [(28, 2026), (27, 2026), (29, 2026)], future_week=(29, 2026)
        )

    assert outcome.degraded is True
    assert outcome.outage_reason == "backend-down"
    assert outcome.weeks == ()
    assert outcome.future_skipped == ()
    assert not (await backoff.status(PROVIDER_PULL, PULL_PROVIDER_ID)).healthy


@pytest.mark.req("FRG-PULL-002")
def test_entry_count_cap_bounds_a_hostile_payload():
    flood = [
        {"series": f"S{i}", "issue": str(i), "shipdate": "2026-07-08"}
        for i in range(50)
    ]
    entries = parse_pull_payload(
        json.dumps(flood).encode(), max_entries=10
    )
    assert len(entries) == 10  # capped, extras dropped


# --- B.3 error-code mapping + outage/degraded-health ------------------------


@pytest.mark.req("FRG-PULL-002")
async def test_619_bad_date_skips_only_that_week(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["week"] == "26":
            return httpx.Response(619)  # bad date for the previous week only
        return httpx.Response(200, json=_sample_entries())

    client = PullSourceClient(_factory(tmp_path, _mock(handler)), SOURCE_URL)
    async with client:
        outcome = await client.fetch_weeks([(26, 2026), (27, 2026)])

    assert outcome.degraded is False  # a 619 is NOT a full outage
    assert outcome.skipped == ((26, 2026),)  # only the bad-date week skipped
    assert [w.week for w in outcome.weeks] == [27]  # the good week still fetched
    assert len(outcome.weeks[0].entries) == 2


@pytest.mark.req("FRG-PULL-002")
async def test_fetch_week_maps_619_to_bad_date(tmp_path):
    client = PullSourceClient(
        _factory(tmp_path, _mock(lambda r: httpx.Response(619))), SOURCE_URL
    )
    async with client:
        with pytest.raises(PullBadDate):
            await client.fetch_week(week=26, year=2026)


@pytest.mark.req("FRG-PULL-002")
async def test_522_backend_down_is_outage_leaves_data_intact_and_marks_degraded(
    tmp_path, db
):
    backoff = ProviderBackoff(db)
    client = PullSourceClient(
        _factory(tmp_path, _mock(lambda r: httpx.Response(522))),
        SOURCE_URL,
        backoff=backoff,
    )
    async with client:
        outcome = await client.fetch_weeks([(26, 2026), (27, 2026)])

    # No week is returned for storage -> area D writes nothing -> stored data
    # left intact; the run is flagged degraded.
    assert outcome.degraded is True
    assert outcome.weeks == ()
    assert outcome.outage_reason == "backend-down"

    # The back-off ladder recorded the outage: the source is now degraded.
    status = await backoff.status(PROVIDER_PULL, PULL_PROVIDER_ID)
    assert not status.healthy

    # ...and it surfaces in the health warnings with a remediation hint. An
    # outage only ever happens while the source is enabled, so health is asked
    # with pull_enabled=True (a disabled source is suppressed — see below).
    warnings = await HealthService(
        db, make_settings(tmp_path, pull_enabled=True), scheduler=None
    ).warnings()
    pull = [w for w in warnings if w.source == "pull-source"]
    assert len(pull) == 1
    assert pull[0].type == "warning"
    assert pull[0].remediation_hint


@pytest.mark.req("FRG-PULL-002")
async def test_disabled_source_suppresses_a_stale_degraded_item(tmp_path, db):
    """Turning the feature off must clear its health item even if a back-off row
    survives from when it was enabled: while disabled the fetch never runs, so
    nothing can reset the ladder, and the item would otherwise read 'degraded'
    forever for a feature the operator has deliberately turned off."""
    backoff = ProviderBackoff(db)
    await backoff.record_failure(PROVIDER_PULL, PULL_PROVIDER_ID, reason="backend-down")
    assert not (await backoff.status(PROVIDER_PULL, PULL_PROVIDER_ID)).healthy

    warnings = await HealthService(
        db, make_settings(tmp_path, pull_enabled=False), scheduler=None
    ).warnings()
    assert not [w for w in warnings if w.source == "pull-source"]


@pytest.mark.req("FRG-PULL-002")
async def test_666_update_required_fast_forwards_the_backoff(tmp_path, db):
    backoff = ProviderBackoff(db)
    client = PullSourceClient(
        _factory(tmp_path, _mock(lambda r: httpx.Response(666))),
        SOURCE_URL,
        backoff=backoff,
    )
    async with client:
        outcome = await client.fetch_weeks([(27, 2026)])

    assert outcome.degraded is True
    assert outcome.outage_reason == "update-required"
    status = await backoff.status(PROVIDER_PULL, PULL_PROVIDER_ID)
    # An update-required signal jumps the ladder rather than stepping one rung.
    assert status.level >= FAST_FORWARD_MIN_LEVEL


@pytest.mark.req("FRG-PULL-002")
async def test_transport_failure_is_an_outage(tmp_path, db):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    backoff = ProviderBackoff(db)
    client = PullSourceClient(
        _factory(tmp_path, _mock(boom)), SOURCE_URL, backoff=backoff
    )
    async with client:
        outcome = await client.fetch_weeks([(27, 2026)])

    assert outcome.degraded is True
    assert outcome.outage_reason == "transport"
    assert not (await backoff.status(PROVIDER_PULL, PULL_PROVIDER_ID)).healthy


@pytest.mark.req("FRG-PULL-002")
async def test_successful_run_clears_a_prior_degraded_state(tmp_path, db):
    backoff = ProviderBackoff(db)
    # Pre-seed a degraded state (as a prior outage would leave it).
    await backoff.record_failure(
        PROVIDER_PULL, PULL_PROVIDER_ID, reason="backend-down"
    )
    assert not (await backoff.status(PROVIDER_PULL, PULL_PROVIDER_ID)).healthy

    client = PullSourceClient(
        _factory(tmp_path, _mock(lambda r: httpx.Response(200, json=_sample_entries()))),
        SOURCE_URL,
        backoff=backoff,
    )
    async with client:
        outcome = await client.fetch_weeks([(27, 2026)])

    assert outcome.degraded is False
    # A single success resets the ladder -> health recovers, warning clears
    # (asked with the source enabled, so the clear is the success, not the gate).
    assert (await backoff.status(PROVIDER_PULL, PULL_PROVIDER_ID)).healthy
    warnings = await HealthService(
        db, make_settings(tmp_path, pull_enabled=True), scheduler=None
    ).warnings()
    assert not [w for w in warnings if w.source == "pull-source"]
