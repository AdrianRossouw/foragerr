"""OPDS Page-Streaming resource-limit config keys (FRG-OPDS-012). The
``opds_pse_*`` caps bound the untrusted archive/image-decode surface; an
out-of-range value is rejected by pydantic validation, and the helper folds the
member/byte caps into a per-request ``ArchiveLimits`` override the endpoints use."""

from __future__ import annotations

import pytest

from foragerr.config import Settings
from foragerr.security.archives import DEFAULT_ARCHIVE_LIMITS, ArchiveLimits


@pytest.fixture
def config_dir(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    return d


@pytest.mark.req("FRG-OPDS-012")
def test_pse_limits_defaults_and_archive_limits_helper(config_dir):
    settings = Settings(config_dir=config_dir)
    assert settings.opds_pse_max_members == 5000
    assert settings.opds_pse_max_page_bytes == 64 * 1024 * 1024
    assert settings.opds_pse_max_pixels == 64_000_000
    assert settings.opds_pse_request_timeout_seconds == 20.0
    assert settings.opds_pse_max_width == 2048

    limits = settings.opds_pse_archive_limits()
    assert isinstance(limits, ArchiveLimits)
    # The member-count cap folds into the per-request LISTING override; total /
    # nesting stay at the shared archive defaults.
    assert limits.max_members == 5000
    # Listability is DECOUPLED from the tight per-page byte cap (FIX-1b): the
    # listing limit's member-size cap stays at the DEFAULT import cap, NOT
    # opds_pse_max_page_bytes — so an archive is streamable iff it passed import,
    # and a single oversized page is refused only at read time (a per-page 502)
    # rather than 404-ing the whole archive. The tight per-page cap therefore does
    # NOT appear here.
    assert limits.max_member_bytes == DEFAULT_ARCHIVE_LIMITS.max_member_bytes
    assert limits.max_member_bytes != settings.opds_pse_max_page_bytes


@pytest.mark.req("FRG-OPDS-012")
@pytest.mark.parametrize(
    "field, bad",
    [
        ("opds_pse_max_members", 0),
        ("opds_pse_max_page_bytes", 0),
        ("opds_pse_max_pixels", 0),
        ("opds_pse_request_timeout_seconds", 0.0),
        ("opds_pse_max_width", 0),
    ],
)
def test_out_of_range_pse_limit_is_rejected(config_dir, field, bad):
    with pytest.raises(Exception) as excinfo:
        Settings(config_dir=config_dir, **{field: bad})
    assert field in str(excinfo.value)
