"""Rate-limiter core mechanics + audit sanitizer (FRG-AUTH-009, unit level).

Drives :class:`RateLimiter` directly on an injectable clock — window arithmetic,
exponential deadline growth + cap, per-key isolation, reset-on-success, registry
eviction bound, and the observation-only global counter that never blocks.
"""

from __future__ import annotations

import pytest

from foragerr.auth.audit import MAX_FIELD_LENGTH, sanitize
from foragerr.auth.ratelimit import (
    BACKOFF_BASE_SECONDS,
    FAILURE_THRESHOLD,
    RateLimiter,
    SeenSourceSet,
    SURFACE_API_KEY,
    SURFACE_BASIC,
    SURFACE_LOGIN,
    WINDOW_SECONDS,
)


def _limiter(clock, **kw):
    return RateLimiter(clock=lambda: clock["t"], **kw)


@pytest.mark.req("FRG-AUTH-009")
def test_below_threshold_never_throttles_at_threshold_it_does():
    """Failures below the threshold leave the key open; the threshold-th failure
    within the window starts the refusal."""
    clock = {"t": 0.0}
    rl = _limiter(clock, threshold=3, window_seconds=100, backoff_base_seconds=10)

    for i in range(2):
        clock["t"] = i
        rl.record_failure("ip", SURFACE_LOGIN)
        assert rl.retry_after("ip", SURFACE_LOGIN) is None  # 1, 2 < threshold

    clock["t"] = 2
    rl.record_failure("ip", SURFACE_LOGIN)  # third — now throttled
    assert rl.retry_after("ip", SURFACE_LOGIN) == pytest.approx(10.0)


@pytest.mark.req("FRG-AUTH-009")
def test_failures_age_out_of_the_window():
    """A sliding window: failures older than the window are pruned, so a key whose
    old failures have expired is no longer throttled."""
    clock = {"t": 0.0}
    rl = _limiter(clock, threshold=3, window_seconds=100, backoff_base_seconds=10)

    for t in (0, 10, 20):
        clock["t"] = t
        rl.record_failure("ip", SURFACE_LOGIN)
    assert rl.retry_after("ip", SURFACE_LOGIN) is not None  # 3 within window

    clock["t"] = 101  # cutoff = 1; the t=0 failure ages out, count drops to 2
    assert rl.retry_after("ip", SURFACE_LOGIN) is None


@pytest.mark.req("FRG-AUTH-009")
def test_deadline_grows_exponentially_and_caps_at_the_window():
    """Each failure beyond the threshold doubles the refusal deadline (base,
    2×base, 4×base, …) up to the window-length cap."""
    clock = {"t": 0.0}
    rl = _limiter(clock, threshold=2, window_seconds=1000, backoff_base_seconds=10)

    # Stack failures with the clock essentially fixed so none age out; check the
    # deadline right after each (now == last failure ⇒ retry_after == deadline).
    expected = [10, 20, 40, 80, 160, 320, 640, 1000, 1000]  # base*2^excess, capped
    for step, want in enumerate(expected):
        rl.record_failure("ip", SURFACE_LOGIN)  # counts 2,3,4,… once past threshold
        if step == 0:
            rl.record_failure("ip", SURFACE_LOGIN)  # reach the threshold first
        assert rl.retry_after("ip", SURFACE_LOGIN) == pytest.approx(want)


@pytest.mark.req("FRG-AUTH-009")
def test_keys_are_isolated_by_ip_and_surface():
    """Throttling one (IP, surface) leaves other IPs and other surfaces open."""
    clock = {"t": 0.0}
    rl = _limiter(clock, threshold=2, window_seconds=100, backoff_base_seconds=10)

    for _ in range(3):
        rl.record_failure("attacker", SURFACE_LOGIN)
    assert rl.retry_after("attacker", SURFACE_LOGIN) is not None

    assert rl.retry_after("operator", SURFACE_LOGIN) is None  # other IP
    assert rl.retry_after("attacker", SURFACE_API_KEY) is None  # other surface
    assert rl.retry_after("attacker", SURFACE_BASIC) is None


@pytest.mark.req("FRG-AUTH-009")
def test_success_resets_the_key():
    """A success clears the burst on its (IP, surface) key — no lockout."""
    clock = {"t": 0.0}
    rl = _limiter(clock, threshold=2, window_seconds=100, backoff_base_seconds=10)

    for _ in range(3):
        rl.record_failure("ip", SURFACE_LOGIN)
    assert rl.retry_after("ip", SURFACE_LOGIN) is not None

    rl.record_success("ip", SURFACE_LOGIN)
    assert rl.retry_after("ip", SURFACE_LOGIN) is None


@pytest.mark.req("FRG-AUTH-009")
def test_registry_is_bounded_by_capacity_oldest_idle_evicted():
    """Distinct source spraying cannot grow the registry without bound: it is
    capped and the oldest-idle key is evicted first."""
    clock = {"t": 0.0}
    rl = _limiter(clock, threshold=2, window_seconds=10_000, capacity=4)

    for i in range(10):
        clock["t"] = i
        rl.record_failure(f"ip-{i}", SURFACE_LOGIN)
    # Never exceeds capacity, and the earliest keys were dropped.
    assert len(rl._windows) == 4
    assert ("ip-0", SURFACE_LOGIN) not in rl._windows
    assert ("ip-9", SURFACE_LOGIN) in rl._windows


@pytest.mark.req("FRG-AUTH-009")
def test_global_counter_reports_but_never_blocks():
    """Failures sprayed from many addresses (none crossing the per-key threshold)
    cross the global per-surface threshold: it reports the rising edge exactly
    once, yet blocks nobody — spraying cannot lock the operator out."""
    clock = {"t": 0.0}
    rl = _limiter(clock, threshold=3, window_seconds=100, backoff_base_seconds=10)

    crossings = 0
    for i in range(6):
        if rl.record_failure(f"ip-{i}", SURFACE_LOGIN):  # one failure per distinct IP
            crossings += 1
        # No single key is anywhere near its own threshold.
        assert rl.retry_after(f"ip-{i}", SURFACE_LOGIN) is None
    assert crossings == 1  # rising edge only, once at the 3rd distinct failure


@pytest.mark.req("FRG-AUTH-009")
def test_defaults_match_the_spec():
    """The module defaults are the spec's 5-per-15-minutes / 30 s base."""
    assert FAILURE_THRESHOLD == 5
    assert WINDOW_SECONDS == 15 * 60
    assert BACKOFF_BASE_SECONDS == 30.0


# --- seen-source set (auth.apikey_source_seen) -------------------------------


@pytest.mark.req("FRG-AUTH-009")
def test_seen_source_first_use_emits_repeats_silent():
    """First successful key use from an IP is fresh; repeats within the window
    are silent (one event per source per window, not per request)."""
    clock = {"t": 0.0}
    seen = SeenSourceSet(ttl_seconds=100, clock=lambda: clock["t"])

    assert seen.observe("1.2.3.4") is True
    assert seen.observe("1.2.3.4") is False
    assert seen.observe("1.2.3.4") is False
    assert seen.observe("5.6.7.8") is True  # a different source is its own event


@pytest.mark.req("FRG-AUTH-009")
def test_seen_source_re_emits_after_ttl_expiry():
    """Once the window passes, the same IP is fresh again (TTL expiry re-emits)."""
    clock = {"t": 0.0}
    seen = SeenSourceSet(ttl_seconds=100, clock=lambda: clock["t"])

    assert seen.observe("1.2.3.4") is True
    clock["t"] = 50
    assert seen.observe("1.2.3.4") is False  # still within window
    clock["t"] = 151  # past the 100 s TTL from the last observation
    assert seen.observe("1.2.3.4") is True


@pytest.mark.req("FRG-AUTH-009")
def test_seen_source_clear_resets_baseline():
    """Clearing (key rotation) makes every IP fresh again."""
    seen = SeenSourceSet(ttl_seconds=100)
    assert seen.observe("1.2.3.4") is True
    assert seen.observe("1.2.3.4") is False
    seen.clear()
    assert seen.observe("1.2.3.4") is True


@pytest.mark.req("FRG-AUTH-009")
def test_seen_source_set_is_bounded():
    """The seen-set is capacity-bounded with oldest-idle eviction — spraying
    distinct sources cannot grow memory without limit."""
    clock = {"t": 0.0}
    seen = SeenSourceSet(ttl_seconds=10_000, capacity=4, clock=lambda: clock["t"])
    for i in range(10):
        clock["t"] = i
        seen.observe(f"ip-{i}")
    assert len(seen._seen) == 4
    assert "ip-0" not in seen._seen and "ip-9" in seen._seen


# --- audit sanitizer ---------------------------------------------------------


@pytest.mark.req("FRG-AUTH-009")
def test_sanitize_strips_control_chars_and_caps_length():
    """Newlines, carriage returns, ANSI escapes, NUL and other control characters
    are removed and the value is truncated to the cap — a crafted username can
    neither break a log line nor forge a second event."""
    injected = "admin\n\r\t\x00\x1b bob"
    out = sanitize(injected)
    assert "\n" not in out and "\r" not in out and "\x00" not in out
    assert "\t" not in out and "\x1b" not in out
    assert out == "admin bob"  # printables + spaces survive, controls gone

    # A forged second event embedded via a newline collapses to inert text.
    forged = sanitize("x\nauth.login.success ip=evil")
    assert "\n" not in forged

    assert sanitize("x" * 500) == "x" * MAX_FIELD_LENGTH
    assert sanitize("normal user") == "normal user"  # ordinary value untouched
