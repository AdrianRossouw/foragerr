"""Unit tests for the cover-URL allowlist evaluator (FRG-META-021).

The single, dependency-free source of truth that both gates (the same-origin
cover proxy and the pull ingest) run. Two properties matter beyond the plain
allow/deny matrix: the public entry points are TOTAL (a malformed authority is
a refusal, never an exception), and ``canonical_cover_url`` yields one stable
stored/fetched form (userinfo/port/query/fragment dropped, path bytes
preserved). Cover URLs here are synthetic paths on the real allowlisted hosts.
"""

from __future__ import annotations

import pytest

from foragerr.covers import (
    MAX_COVER_URL_LENGTH,
    canonical_cover_url,
    cover_url_allowed,
    target_allowed,
)

# A synthetic cover on each allowlisted shape.
CV = "https://comicvine.gamespot.com/a/uploads/scale_small/x.png"
CV_SUB = "https://media.comicvine.gamespot.com/a/uploads/x.png"
CV_DOT = "https://comicvine.com/a/uploads/x.png"
S3 = "https://s3.amazonaws.com/comicgeeks/comics/covers/large-90210.jpg"

#: A homoglyph host that stays NON-ASCII after ``.hostname`` lowercasing
#: (Cyrillic small o, U+043E) — the ascii-host guard must refuse it rather than
#: let ``str.lower`` desync from a client's IDNA parsing.
CYRILLIC_HOST = "comicvine.gamespot.cоm"


ALLOWED = [
    S3,
    CV,
    CV_SUB,  # dot-boundary subdomain of a CV host
    CV_DOT,
    "https://s3.amazonaws.com:443/comicgeeks/x.jpg",  # explicit default port
    "https://comicvine.gamespot.com:443/a/x.png",
]

DENIED = [
    "https://s3.amazonaws.com/other-bucket/x.jpg",  # wrong bucket
    "https://s3.amazonaws.com/comicgeeks-evil/x.jpg",  # prefix lookalike, no boundary
    "https://s3.amazonaws.com//comicgeeks/x.jpg",  # empty leading segment
    # Virtual-hosted bucket subdomain: exact-host rule refuses it.
    "https://comicgeeks.s3.amazonaws.com/comics/covers/x.jpg",
    "https://comicgeeks.s3.amazonaws.com/comicgeeks/x.jpg",
    "https://u:p@comicvine.gamespot.com/a/x.png",  # userinfo
    "https://comicvine.gamespot.com:22/a/x.png",  # non-default port
    "https://s3.amazonaws.com:8443/comicgeeks/x.jpg",  # non-default port
    f"https://{CYRILLIC_HOST}/a/x.png",  # non-ASCII host
    "https://s3.amazonaws.com/comicgeeks/..;/x.jpg",  # ..-prefixed segment
    "https://s3.amazonaws.com/comicgeeks/%c0%ae%c0%ae/x.jpg",  # overlong UTF-8 dots
    "https://s3.amazonaws.com/comicgeeks/%2e%2e/x.jpg",  # encoded dot-segment
    "https://s3.amazonaws.com/comicgeeks/a\\b/x.jpg",  # backslash
    "https://s3.amazonaws.com/comicgeeks/a\x01b.jpg",  # control char in path
    "http://comicvine.gamespot.com/a/x.png",  # non-HTTPS
    "https://[::1/comicgeeks/x.jpg",  # malformed authority (unbalanced bracket)
    "https://evil[.]com]/comicgeeks/x.jpg",  # malformed authority (stray bracket)
]

#: A fuzz list of authorities that ``urlsplit`` itself may choke on — the point
#: is only that the evaluator NEVER raises on any of them.
FUZZ = [
    "",
    "https://",
    "://x",
    "https://[",
    "https://]",
    "ht!tp://x",
    "https://a b/c",
    "https://%/x",
    "https://s3.amazonaws.com/comicgeeks/%zz",  # undecodable escape
    "https://s3.amazonaws.com/comicgeeks/%c0%ae",  # overlong, dangling
    "https://例え.テスト/x",  # non-ASCII IDN
    "https://[::1/comicgeeks/x.jpg",
    "https://evil[.]com]/comicgeeks/x.jpg",
]


@pytest.mark.req("FRG-META-021")
@pytest.mark.parametrize("url", ALLOWED)
def test_allowed_cover_urls(url):
    assert cover_url_allowed(url) is True


@pytest.mark.req("FRG-META-021")
@pytest.mark.parametrize("url", DENIED)
def test_denied_cover_urls(url):
    assert cover_url_allowed(url) is False


@pytest.mark.req("FRG-META-021")
@pytest.mark.parametrize("url", FUZZ + DENIED + ALLOWED)
def test_evaluator_is_total_and_never_raises(url):
    """The trust-boundary entry points must fail closed to a bool, never an
    exception, whatever the input."""
    result = cover_url_allowed(url)
    assert isinstance(result, bool)


@pytest.mark.req("FRG-META-021")
def test_ascii_host_guard_refuses_non_ascii_at_the_rule_level():
    """The rule refuses a non-ASCII host outright rather than lowercasing it
    into an ASCII lookalike that could match a rule."""
    assert (
        target_allowed(
            "https", "comicvine.gamespot.com", "/comicgeeks/x.jpg", ascii_host=False
        )
        is False
    )
    # And the always-on parts of the rule, checked directly:
    assert target_allowed("https", "s3.amazonaws.com", "/comicgeeks/x.jpg") is True
    assert (
        target_allowed(
            "https", "s3.amazonaws.com", "/comicgeeks/x.jpg", userinfo_present=True
        )
        is False
    )
    assert (
        target_allowed("https", "comicvine.gamespot.com", "/x.png", port=22) is False
    )
    assert target_allowed("http", "comicvine.gamespot.com", "/x.png") is False


# --- canonical form ----------------------------------------------------------


@pytest.mark.req("FRG-META-021")
def test_canonical_drops_port_query_and_fragment():
    assert (
        canonical_cover_url("https://comicvine.gamespot.com:443/a/x.png?cb=9#frag")
        == "https://comicvine.gamespot.com/a/x.png"
    )


@pytest.mark.req("FRG-META-021")
def test_canonical_preserves_path_bytes():
    """Percent-escapes in the path survive verbatim — the fetched URL is the
    caller's wire form, never a decoded rebuild that could change what the
    remote receives."""
    assert (
        canonical_cover_url("https://s3.amazonaws.com/comicgeeks/a%2fb.jpg")
        == "https://s3.amazonaws.com/comicgeeks/a%2fb.jpg"
    )
    assert (
        canonical_cover_url("https://comicvine.gamespot.com/%63over.png")
        == "https://comicvine.gamespot.com/%63over.png"
    )


@pytest.mark.req("FRG-META-021")
def test_canonical_returns_none_for_disallowed_including_userinfo():
    for url in (
        "https://evil.example/x.png",  # off-host
        "https://u:p@comicvine.gamespot.com/a/x.png",  # userinfo — refused, not stripped
        "http://comicvine.gamespot.com/a/x.png",  # non-HTTPS
        "/assets/images/no-cover-lg.jpg",  # relative placeholder
    ):
        assert canonical_cover_url(url) is None, url


@pytest.mark.req("FRG-META-021")
def test_canonical_refuses_over_length():
    long_path = "/" + "a" * (MAX_COVER_URL_LENGTH + 50) + ".png"
    assert len("https://comicvine.gamespot.com" + long_path) > MAX_COVER_URL_LENGTH
    assert canonical_cover_url("https://comicvine.gamespot.com" + long_path) is None


@pytest.mark.req("FRG-META-021")
def test_canonical_is_idempotent_across_query_variants():
    """Two spellings of one image (differing volatile cache-buster) collapse to
    one canonical form — a stable stored value and a stable proxy cache key."""
    a = canonical_cover_url(S3 + "?1780169968")
    b = canonical_cover_url(S3 + "?1780900123")
    assert a == b == S3
