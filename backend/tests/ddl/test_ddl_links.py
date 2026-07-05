"""Link enumeration, ordering, paywall rejection + dispatch completeness.

Covers FRG-DDL-004 (table-driven per-quality/host enumeration + selection order
+ paywall rejection) and the FRG-DDL-005 dispatch-table completeness test that
regression-proofs mylar-ddl's ``GC_Mirror``/``GC-Mirror`` typo.
"""

from __future__ import annotations

import pytest

from foragerr.ddl.adapter_v1 import parse_post_page, url_host
from foragerr.ddl.links import (
    DISPATCH,
    DownloadStrategy,
    Host,
    LinkCandidate,
    QualityTier,
    classify_host,
    classify_quality,
    dispatch_for,
    is_paywall_host,
    order_candidates,
    parse_host_priority,
)
from ddl_support import fixture

BASE = "https://getcomics.org"


def _enumerate(html: str) -> list[LinkCandidate]:
    out: list[LinkCandidate] = []
    for raw in parse_post_page(html, base_url=BASE):
        host = classify_host(raw.host_label)
        if host is None:
            continue
        if is_paywall_host(url_host(raw.url)):
            continue
        handler = dispatch_for(host)
        out.append(
            LinkCandidate(
                host=host,
                quality=classify_quality(raw.quality_label),
                link_type=handler.link_type,
                url=raw.url,
                strategy=handler.strategy,
            )
        )
    return out


@pytest.mark.req("FRG-DDL-005")
def test_dispatch_table_covers_every_host_and_link_type():
    # Every Host resolves to a concrete handler — no unmapped or misspelled
    # entry can exist (mylar-ddl's GC_Mirror vs GC-Mirror typo, §3.3).
    for host in Host:
        handler = dispatch_for(host)
        assert handler.host is host
        assert handler.link_type and "_" not in handler.link_type
        assert handler.strategy in (
            DownloadStrategy.DIRECT,
            DownloadStrategy.UNSUPPORTED,
        )
    # Link-type labels are unique across the whole table.
    link_types = [h.link_type for h in DISPATCH.values()]
    assert len(link_types) == len(set(link_types)) == len(Host)


@pytest.mark.req("FRG-DDL-004")
def test_links_enumerated_per_quality_and_host():
    candidates = _enumerate(fixture("post_page.html"))
    combos = {(c.host, c.quality) for c in candidates}
    assert (Host.MAIN, QualityTier.HD_UPSCALED) in combos
    assert (Host.MIRROR, QualityTier.HD_UPSCALED) in combos
    assert (Host.MEGA, QualityTier.HD_UPSCALED) in combos
    assert (Host.MAIN, QualityTier.SD) in combos
    assert (Host.PIXELDRAIN, QualityTier.SD) in combos


@pytest.mark.req("FRG-DDL-004")
def test_paywall_and_readonline_never_enumerated():
    candidates = _enumerate(fixture("post_page.html"))
    assert all("sh.st" not in c.url for c in candidates)  # paywall rejected
    assert all(c.host in set(Host) for c in candidates)  # read-online dropped


@pytest.mark.req("FRG-DDL-004")
def test_selection_follows_configured_host_order():
    candidates = _enumerate(fixture("post_page.html"))
    order = parse_host_priority("main,mirror,pixeldrain,mediafire,mega")
    ordered = order_candidates(
        candidates, host_priority=order, prefer_upscaled=True
    )
    # main preferred first; its HD-Upscaled beats its SD; mega (last) trails.
    assert ordered[0].host is Host.MAIN
    assert ordered[0].quality is QualityTier.HD_UPSCALED
    assert ordered[-1].host is Host.MEGA


@pytest.mark.req("FRG-DDL-004")
def test_prefer_upscaled_toggle_changes_quality_order():
    candidates = _enumerate(fixture("post_page.html"))
    order = parse_host_priority("main,mirror,pixeldrain,mediafire,mega")
    main_only = [c for c in candidates if c.host is Host.MAIN]
    up = order_candidates(main_only, host_priority=order, prefer_upscaled=True)
    down = order_candidates(main_only, host_priority=order, prefer_upscaled=False)
    assert up[0].quality is QualityTier.HD_UPSCALED
    assert down[0].quality is QualityTier.SD
