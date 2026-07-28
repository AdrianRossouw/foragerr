"""Every ComicVine construction site's lane, enumerated (FRG-META-022).

``test_api_cv_lanes.py`` pins the INTERACTIVE sites by driving them. This is the
other half, and it is the half that cannot be caught by driving anything: the
lane is declared once, at construction (design D2), so the set of construction
sites IS the contract — and a set silently loses members, and silently gains
them. A background site that forgets its tag is invisible (``batch`` is the
default, so it behaves correctly by luck); a background site that reaches
ComicVine through a helper someone tagged ``interactive`` for their own good
reasons spends the operator's reserve, and nothing complains until the night a
search is refused while a 1,318-item auto-sync runs.

So the census below is a whole-tree AST scan rather than a set of runtime
assertions. It fails on a NEW construction site as loudly as on a changed one,
which a recorder wrapping ``__init__`` cannot do — an untested new site is
exactly the member that goes missing.

Three things the census cannot see, asserted directly beneath it: the two
sites whose lane is a parameter (their defaults are the real contract), the
auto-sync add path that threads one through, and the covers cache, which spends
through the gate rather than a client.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from foragerr.metadata.ratelimit import LANE_BATCH, LANE_INTERACTIVE

SRC = Path(__file__).resolve().parents[1] / "src" / "foragerr"

#: Marker for a site whose lane is supplied by its caller — the value is a name,
#: not a literal, so the census records the delegation and the DEFAULT is pinned
#: separately below (a caller-supplied lane is only as good as what it falls
#: back to).
CALLER_SUPPLIED = "<caller-supplied>"

#: Every ``ComicVineClient(...)`` in the tree, by module, with the lane each one
#: declares. Adding a site means adding a line here — deliberately, with the
#: question "is anybody waiting on this?" answered on the record.
EXPECTED_SITES = {
    "api/config_resources.py": [LANE_INTERACTIVE],  # the Test button
    "api/library_import.py": [LANE_INTERACTIVE],  # import volume override
    "api/series.py": [LANE_INTERACTIVE, LANE_INTERACTIVE],  # lookup + suggest
    "creators/bibliography.py": [LANE_BATCH],  # background creator walk
    "library/flows/add.py": [CALLER_SUPPLIED],  # operator add OR auto-sync
    "library/flows/library_import.py": [LANE_INTERACTIVE],  # import scan
    "library/flows/refresh.py": [LANE_BATCH],  # the scheduled refresh
    "sources/enrich.py": [CALLER_SUPPLIED],  # enrichment OR operator restore
}


def _declared_lanes(tree: ast.AST) -> list[str]:
    """The lane every ``ComicVineClient(...)`` in one module declares.

    An omitted ``lane=`` records the class default rather than "unknown": the
    default IS a declaration, and the whole design rests on it being ``batch``.
    """
    lanes: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "ComicVineClient":
            continue
        keyword = next((k for k in node.keywords if k.arg == "lane"), None)
        if keyword is None:
            lanes.append(LANE_BATCH)  # the class default
        elif isinstance(keyword.value, ast.Constant):
            lanes.append(str(keyword.value.value))
        else:
            lanes.append(CALLER_SUPPLIED)
    return lanes


@pytest.mark.req("FRG-META-022")
def test_every_comicvine_construction_site_declares_a_reviewed_lane():
    """The census. A new site, a moved site, or a re-tagged site all fail here
    until the table above is updated — which is the review this design needs and
    the only place it can be enforced."""
    found = {}
    for path in sorted(SRC.rglob("*.py")):
        lanes = _declared_lanes(ast.parse(path.read_text()))
        if lanes:
            found[str(path.relative_to(SRC))] = lanes

    assert found == EXPECTED_SITES


@pytest.mark.req("FRG-META-022")
def test_the_two_delegated_lanes_default_to_the_right_side():
    """The two caller-supplied sites fall back in OPPOSITE directions, and each
    default is the safe answer for that function's ordinary caller.

    ``add_series`` defaults interactive because almost every add is an operator
    clicking Add and watching; auto-sync, the one background caller, says so.
    ``build_cv_client`` defaults batch because its own callers ARE the nightly
    enrichment run; the operator endpoints say so. Getting either backwards
    silently misroutes the majority of that function's traffic.
    """
    import inspect

    from foragerr.library.flows.add import add_series
    from foragerr.sources.enrich import build_cv_client

    assert inspect.signature(add_series).parameters["lane"].default == (
        LANE_INTERACTIVE
    )
    assert inspect.signature(build_cv_client).parameters["lane"].default == LANE_BATCH


@pytest.mark.req("FRG-META-022")
async def test_the_covers_cache_spends_batch_through_the_gate(tmp_path):
    """Covers reach the budget through the gate DIRECTLY rather than through a
    client, so no census of client constructions can see them. The lane is
    asserted on the gate's own ledger instead."""
    import httpx

    from foragerr.http import HttpClientFactory
    from foragerr.metadata import ratelimit
    from foragerr.metadata.covers import COVER_BUDGET_BUCKET, cache_cover
    from foragerr.metadata.ratelimit import _lane_of

    from http_support import PUBLIC_V4, StubResolver, make_settings

    ratelimit.reset_gate()
    settings = make_settings(tmp_path, comicvine_api_key="k")
    factory = HttpClientFactory(
        settings,
        resolver=StubResolver({"comicvine.gamespot.com": [PUBLIC_V4]}),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"\xff\xd8\xffJPG")
        ),
    )
    try:
        await cache_cover(
            "https://comicvine.gamespot.com/a/uploads/original/x.jpg",
            tmp_path / "covers" / "1.jpg",
            factory=factory,
            settings=settings,
        )
        ledger = ratelimit.gate()._ledgers[COVER_BUDGET_BUCKET]
        assert [_lane_of(s) for s in ledger] == [LANE_BATCH]
    finally:
        ratelimit.reset_gate()
