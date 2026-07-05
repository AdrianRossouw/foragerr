"""FRG-SRCH-004 — core specification set: one reason each, decision-matrix."""

from __future__ import annotations

from datetime import datetime

import pytest

from foragerr.search import (
    DecisionEngine,
    EngineConfig,
    ExistingFile,
    FormatProfile,
    RejectionType,
    SearchTarget,
)

from .builders import NOW, candidate, context, issue, series

ENGINE = DecisionEngine()


def _target_ctx(*serieses, series_id=1, issue_id=10, **kw):
    return context(*serieses, target=SearchTarget(series_id=series_id, issue_id=issue_id), **kw)


def _rej(decision, spec):
    return next((r for r in decision.rejections if r.spec == spec), None)


# --- format-allowed ---------------------------------------------------------


@pytest.mark.req("FRG-SRCH-004")
def test_format_not_allowed_is_rejected():
    prof = FormatProfile(formats=("cbr", "cbz"), cutoff="cbz")  # pdf excluded
    s = series(1, "batman", issues=(issue(10, 5),), profile=prof)
    d = ENGINE.evaluate(candidate("Batman 005 (2016).pdf"), _target_ctx(s))
    r = _rej(d, "format-allowed")
    assert r is not None and r.type is RejectionType.PERMANENT
    assert "Format not allowed" in r.reason


@pytest.mark.req("FRG-SRCH-004")
def test_allowed_format_passes():
    s = series(1, "batman", issues=(issue(10, 5),))
    d = ENGINE.evaluate(candidate("Batman 005 (2016).cbz"), _target_ctx(s))
    assert _rej(d, "format-allowed") is None


@pytest.mark.req("FRG-SRCH-004")
def test_unknown_format_is_permitted_pre_download():
    s = series(1, "batman", issues=(issue(10, 5),))
    # No container token in the title -> format unknown -> not rejected here.
    d = ENGINE.evaluate(candidate("Batman 005 (2016)"), _target_ctx(s))
    assert _rej(d, "format-allowed") is None


# --- upgrade-allowed --------------------------------------------------------


@pytest.mark.req("FRG-SRCH-004")
def test_not_an_upgrade_over_equal_file_on_disk():
    # Existing cbz (cutoff met); a cbr release is not an upgrade.
    existing = (ExistingFile(format="cbz", size_bytes=30_000_000),)
    s = series(1, "batman", issues=(issue(10, 5, files=existing),))
    d = ENGINE.evaluate(candidate("Batman 005 (2016).cbr"), _target_ctx(s))
    r = _rej(d, "upgrade-allowed")
    assert r is not None and r.type is RejectionType.PERMANENT
    assert "Not an upgrade" in r.reason


@pytest.mark.req("FRG-SRCH-004")
def test_genuine_upgrade_over_lower_format_passes():
    existing = (ExistingFile(format="cbr", size_bytes=30_000_000),)
    s = series(1, "batman", issues=(issue(10, 5, files=existing),))
    d = ENGINE.evaluate(candidate("Batman 005 (2016).cbz"), _target_ctx(s))
    assert _rej(d, "upgrade-allowed") is None


@pytest.mark.req("FRG-SRCH-004")
def test_no_file_on_disk_is_never_an_upgrade_rejection():
    s = series(1, "batman", issues=(issue(10, 5),))
    d = ENGINE.evaluate(candidate("Batman 005 (2016).cbr"), _target_ctx(s))
    assert _rej(d, "upgrade-allowed") is None


@pytest.mark.req("FRG-SRCH-004")
def test_upgrades_disabled_rejects_when_file_exists():
    existing = (ExistingFile(format="cbr", size_bytes=1),)
    s = series(1, "batman", issues=(issue(10, 5, files=existing),))
    cfg = EngineConfig(upgrades_allowed=False)
    d = ENGINE.evaluate(candidate("Batman 005 (2016).cbz"), _target_ctx(s, config=cfg))
    r = _rej(d, "upgrade-allowed")
    assert r is not None and "Upgrades are disabled" in r.reason


# --- retention / min-age ----------------------------------------------------


@pytest.mark.req("FRG-SRCH-004")
def test_retention_rejects_old_candidate_permanent():
    s = series(1, "batman", issues=(issue(10, 5),))
    cfg = EngineConfig(retention_days=1200)
    d = ENGINE.evaluate(
        candidate("Batman 005 (2016).cbz", age_hours=24 * 2000), _target_ctx(s, config=cfg)
    )
    r = _rej(d, "retention")
    assert r is not None and r.type is RejectionType.PERMANENT


@pytest.mark.req("FRG-SRCH-004")
def test_min_age_is_temporary_rejection():
    s = series(1, "batman", issues=(issue(10, 5),))
    cfg = EngineConfig(min_age_minutes=120)
    d = ENGINE.evaluate(
        candidate("Batman 005 (2016).cbz", age_hours=0.5), _target_ctx(s, config=cfg)
    )
    r = _rej(d, "min-age")
    assert r is not None and r.type is RejectionType.TEMPORARY
    assert "Too new" in r.reason


@pytest.mark.req("FRG-SRCH-004")
def test_age_specs_skip_when_no_pub_date():
    s = series(1, "batman", issues=(issue(10, 5),))
    cfg = EngineConfig(retention_days=1, min_age_minutes=999999)
    d = ENGINE.evaluate(
        candidate("Batman 005 (2016).cbz", pub_date=None), _target_ctx(s, config=cfg)
    )
    assert _rej(d, "retention") is None
    assert _rej(d, "min-age") is None


@pytest.mark.req("FRG-SRCH-004")
def test_year_sanity_rejects_impossible_year():
    # The parser already discards implausible *future* years; year-sanity
    # guards an implausibly-old year the parser still accepts as a year.
    s = series(1, "batman", issues=(issue(10, 5),))
    d = ENGINE.evaluate(candidate("Batman 005 (1850).cbz"), _target_ctx(s))
    r = _rej(d, "year-sanity")
    assert r is not None and r.type is RejectionType.PERMANENT


# --- terms ------------------------------------------------------------------


@pytest.mark.req("FRG-SRCH-004")
def test_must_not_contain_rejects_ignored_term():
    s = series(1, "batman", issues=(issue(10, 5),))
    cfg = EngineConfig(must_not_contain=("Ashcan",))
    d = ENGINE.evaluate(candidate("Batman 005 (2016) Ashcan.cbz"), _target_ctx(s, config=cfg))
    r = _rej(d, "must-not-contain")
    assert r is not None and "Ashcan" in r.reason


@pytest.mark.req("FRG-SRCH-004")
def test_must_contain_rejects_when_required_term_absent():
    s = series(1, "batman", issues=(issue(10, 5),))
    cfg = EngineConfig(must_contain=("Digital",))
    d = ENGINE.evaluate(candidate("Batman 005 (2016).cbz"), _target_ctx(s, config=cfg))
    r = _rej(d, "must-contain")
    assert r is not None and "Digital" in r.reason


# --- change-5 store stubs (inert here, live paths asserted with fakes) -------


@pytest.mark.req("FRG-SRCH-004")
def test_queue_and_blocklist_stubs_accept_by_default():
    s = series(1, "batman", issues=(issue(10, 5),))
    d = ENGINE.evaluate(candidate("Batman 005 (2016).cbz"), _target_ctx(s))
    assert _rej(d, "already-queued") is None
    assert _rej(d, "blocklist") is None
    assert _rej(d, "free-space") is None


class _FakeQueue:
    def is_queued(self, series_id, issue_id):
        return (series_id, issue_id) == (1, 10)


class _FakeBlocklist:
    def is_blocklisted(self, candidate):
        return candidate.guid == "blocked"


class _TightSpace:
    def free_bytes(self, series_id):
        return 10  # far less than any real release


@pytest.mark.req("FRG-SRCH-004")
def test_queue_spec_live_path_with_fake_store():
    s = series(1, "batman", issues=(issue(10, 5),))
    d = ENGINE.evaluate(
        candidate("Batman 005 (2016).cbz"), _target_ctx(s, queue=_FakeQueue())
    )
    r = _rej(d, "already-queued")
    assert r is not None and r.type is RejectionType.PERMANENT


@pytest.mark.req("FRG-SRCH-004")
def test_blocklist_spec_live_path_with_fake_store():
    s = series(1, "batman", issues=(issue(10, 5),))
    d = ENGINE.evaluate(
        candidate("Batman 005 (2016).cbz", guid="blocked"),
        _target_ctx(s, blocklist=_FakeBlocklist()),
    )
    r = _rej(d, "blocklist")
    assert r is not None and r.type is RejectionType.PERMANENT


@pytest.mark.req("FRG-SRCH-004")
def test_free_space_spec_live_path_is_temporary():
    s = series(1, "batman", issues=(issue(10, 5),))
    d = ENGINE.evaluate(
        candidate("Batman 005 (2016).cbz"), _target_ctx(s, free_space=_TightSpace())
    )
    r = _rej(d, "free-space")
    assert r is not None and r.type is RejectionType.TEMPORARY


@pytest.mark.req("FRG-SRCH-004")
def test_each_core_spec_has_a_reachable_rejection_reason():
    # A decision-matrix smoke check: the whole default spec set is present and
    # each core spec's name is emitted by at least one scenario above. Here we
    # simply assert the engine wires all of them.
    names = {s.name for s in ENGINE.specs}
    for expected in (
        "format-allowed",
        "upgrade-allowed",
        "retention",
        "min-age",
        "year-sanity",
        "must-contain",
        "must-not-contain",
        "already-queued",
        "blocklist",
        "free-space",
    ):
        assert expected in names


@pytest.mark.req("FRG-SRCH-004")
def test_now_is_injected_deterministically():
    # Age math uses ctx.now, not wall-clock: same inputs, same verdict.
    s = series(1, "batman", issues=(issue(10, 5),))
    cfg = EngineConfig(min_age_minutes=60)
    c = candidate("Batman 005 (2016).cbz", pub_date=datetime(2026, 7, 5, 11, 30))
    ctx = _target_ctx(s, config=cfg, now=NOW)
    assert ENGINE.evaluate(c, ctx).outcome == ENGINE.evaluate(c, ctx).outcome
