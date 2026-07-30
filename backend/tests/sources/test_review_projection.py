"""The review list's server-computed presentation (FRG-UI-029, FRG-SRC-004/015):
the containment DISPLAY merge, the parsed within-group sort key, and the
duplicate-set fields on the entitlement resource.

The merge and the sort key both exist so the client never re-derives either — a
second fold or a second name parse would drift from the one the server writes
proposals with. The regression that guards that bargain is here too: widening
the display key must NOT widen the FRG-SRC-014 write-side sweep.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from conftest import running_app
from foragerr.sources import ratelimit, repo, review
from foragerr.sources.matching import group_key, merge_display_groups, sort_ordinals
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.service import run_sync
from foragerr.sources.settings import HumbleSettings
from http_support import make_settings
from sources_support import make_factory, order_handler

GAMEKEY = "gamekey-example-bundle"

#: One franchise under two title forms: the second spells the series out inside
#: a longer title, so the folds differ by an exact contiguous token run.
SAGA_SHORT = "Example Saga Vol. 2"
SAGA_LONG = "THE FIRST TALE OF EXAMPLE SAGA"
UNRELATED = "Unrelated Chronicle #4"


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


@pytest.fixture
async def app_client(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    async with running_app(make_settings(cfg)) as (_app, client):
        yield client


def _order(items: list[tuple[str, str, str]]) -> bytes:
    return json.dumps(
        {
            "gamekey": GAMEKEY,
            "product": {
                "machine_name": "example_bundle",
                "human_name": "Example Bundle",
            },
            "subproducts": [
                {
                    "machine_name": machine_name,
                    "human_name": human_name,
                    "publisher": "Example Comics",
                    "downloads": [
                        {
                            "platform": "ebook",
                            "download_struct": [
                                {
                                    "name": "CBZ",
                                    "md5": md5,
                                    "file_size": 1024,
                                    "url": {
                                        "web": f"https://example.com/{machine_name}.cbz"
                                    },
                                }
                            ],
                        }
                    ],
                }
                for machine_name, human_name, md5 in items
            ],
        }
    ).encode()


async def _populate(app, items: list[tuple[str, str, str]]) -> int:
    db = app.state.db
    source = await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Example Store",
        settings=HumbleSettings(session_cookie="SYNTH-COOKIE"),
        connection_state="connected",
    )
    factory = make_factory(
        app.state.settings.config_dir,
        httpx.MockTransport(
            order_handler(
                list_body=json.dumps([{"gamekey": GAMEKEY}]).encode(),
                order_bodies={GAMEKEY: _order(items)},
            )
        ),
    )
    await run_sync(db, factory, source, min_interval=0.0)
    return source.id


# --- the containment display merge -------------------------------------------


@pytest.mark.req("FRG-UI-029")
def test_a_contained_fold_key_merges_into_one_display_group():
    keys = [group_key(SAGA_SHORT), group_key(SAGA_LONG), group_key(UNRELATED)]
    merged = merge_display_groups(keys)

    # The label is the CONTAINED (shortest) key — the part every member shares.
    assert merged[group_key(SAGA_SHORT)] == group_key(SAGA_SHORT)
    assert merged[group_key(SAGA_LONG)] == group_key(SAGA_SHORT)
    assert merged[group_key(UNRELATED)] == group_key(UNRELATED)


@pytest.mark.req("FRG-UI-029")
def test_the_display_merge_is_order_independent_along_a_chain():
    chain = ["alpha beta", "alpha beta gamma", "delta alpha beta gamma"]
    forward = merge_display_groups(chain)
    reverse = merge_display_groups(list(reversed(chain)))

    assert forward == reverse
    # Each key attaches to its LONGEST container, and following those single
    # edges still reunites a genuine chain of title forms into one group,
    # labelled by the part all of them share.
    assert set(forward.values()) == {"alpha beta"}


@pytest.mark.req("FRG-UI-029")
def test_a_single_token_key_is_never_merged_into_a_longer_one():
    """A one-word fold key is a word, not a title: it sits inside every key that
    happens to mention it, so treating it as a needle made it a container for
    unrelated franchises."""
    merged = merge_display_groups(["example force", "example force academy", "force"])

    assert merged["force"] == "force"  # its own group, alone
    assert merged["example force"] == "example force"
    assert merged["example force academy"] == "example force"


@pytest.mark.req("FRG-UI-029")
def test_two_one_word_series_and_the_title_naming_both_stay_apart():
    """Two single-token series plus a crossover title containing both: three
    distinct titles, three groups — never one group holding all of them."""
    merged = merge_display_groups(["alpha", "beta", "alpha versus beta"])

    assert merged == {
        "alpha": "alpha",
        "beta": "beta",
        "alpha versus beta": "alpha versus beta",
    }


@pytest.mark.req("FRG-UI-029")
def test_one_needle_never_welds_two_unrelated_containers_together():
    """The runaway shape: a shared two-token run sits inside two longer keys
    that contain nothing of each other. The needle joins the LONGER of them and
    the other stays its own group, instead of the three collapsing into one."""
    merged = merge_display_groups(
        ["alpha beta", "alpha beta gamma delta", "epsilon alpha beta"]
    )

    assert merged["alpha beta"] == "alpha beta"
    assert merged["alpha beta gamma delta"] == "alpha beta"
    assert merged["epsilon alpha beta"] == "epsilon alpha beta"


@pytest.mark.req("FRG-UI-029")
def test_the_display_merge_holds_its_shape_across_shuffles():
    """Determinism at listing scale: no ordering of the same key set may produce
    a different grouping (the review list is built from whatever order the query
    returns)."""
    import random

    keys = [
        "example saga",
        "example saga academy",
        "example saga academy annual",
        "example chronicle",
        "example chronicle omnibus",
        "saga",
        "chronicle",
        "unrelated example title",
    ]
    expected = merge_display_groups(keys)
    rng = random.Random(20260730)
    for _ in range(20):
        shuffled = keys[:]
        rng.shuffle(shuffled)
        assert merge_display_groups(shuffled) == expected
    # Eight keys, and the merge leaves five distinct groups — the two genuine
    # chains, plus the three keys nothing properly contains.
    assert len(set(expected.values())) == 5


@pytest.mark.req("FRG-UI-029")
def test_the_ungroupable_key_never_merges():
    merged = merge_display_groups(["", "anything", ""])

    assert merged.get("") is None  # never a member of any display group
    assert merged["anything"] == "anything"


@pytest.mark.req("FRG-SRC-014")
async def test_the_display_merge_does_not_widen_the_write_side_sweep(
    app_client, tmp_path
):
    """The sanctioned divergence, pinned: rows that render under ONE display
    group but fold to different keys are NOT swept together."""
    app = app_client.app
    db = app.state.db
    source_id = await _populate(
        app,
        [
            ("saga_short", SAGA_SHORT, "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"),
            ("saga_long", SAGA_LONG, "1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a"),
        ],
    )
    rows = {r.machine_name: r for r in await repo.list_entitlements(db, source_id)}
    assert (
        merge_display_groups([group_key(SAGA_SHORT), group_key(SAGA_LONG)])[
            group_key(SAGA_LONG)
        ]
        == group_key(SAGA_SHORT)
    )

    swept = await review._reresolve_sibling_proposals_by_group(
        db,
        source_id=source_id,
        group_key=group_key(SAGA_SHORT),
        series_id=4242,
        series_title="Example Saga",
        exclude_entitlement_id=rows["saga_short"].id,
    )

    assert swept == 0
    long_row = await repo.get_entitlement(db, rows["saga_long"].id)
    assert long_row.proposed_series_id is None


# --- the parsed sort key ------------------------------------------------------


@pytest.mark.req("FRG-UI-029")
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Example Saga Vol. 2", (2, None)),
        ("Example Saga #12", (None, "12")),
        ("Example Saga Volume 10", (10, None)),
        ("Example Saga", (None, None)),
    ],
)
def test_sort_ordinals_come_from_the_one_parser(name, expected):
    assert sort_ordinals(name) == expected


# --- the resource shape -------------------------------------------------------


@pytest.mark.req("FRG-SRC-015")
async def test_the_listing_carries_the_review_presentation_fields(app_client):
    app = app_client.app
    source_id = await _populate(
        app,
        [
            ("saga_v2", SAGA_SHORT, "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"),
            ("saga_long", SAGA_LONG, "1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a"),
        ],
    )

    rows = (
        await app_client.get(f"/api/v1/sources/{source_id}/entitlements")
    ).json()
    by_name = {row["machine_name"]: row for row in rows}

    assert {
        "duplicate_of",
        "duplicate_count",
        "duplicate_bundles",
        "display_group_key",
        "volume_ordinal",
        "issue_number",
    } <= set(by_name["saga_v2"])
    assert by_name["saga_v2"]["volume_ordinal"] == 2
    assert by_name["saga_v2"]["issue_number"] is None
    # Different fold keys, one display group.
    assert by_name["saga_v2"]["group_key"] != by_name["saga_long"]["group_key"]
    assert (
        by_name["saga_v2"]["display_group_key"]
        == by_name["saga_long"]["display_group_key"]
    )
    assert by_name["saga_v2"]["duplicate_count"] == 0
    assert by_name["saga_v2"]["duplicate_bundles"] == []


@pytest.mark.req("FRG-SRC-015")
async def test_the_canonical_row_discloses_its_copies_through_the_surface(app_client):
    app = app_client.app
    db = app.state.db
    source_id = await _populate(
        app,
        [
            ("saga_v2", SAGA_SHORT, "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"),
            ("saga_v2_again", SAGA_SHORT, "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"),
        ],
    )
    rows = {r.machine_name: r for r in await repo.list_entitlements(db, source_id)}

    listing = (
        await app_client.get(f"/api/v1/sources/{source_id}/entitlements")
    ).json()
    by_name = {row["machine_name"]: row for row in listing}

    assert by_name["saga_v2"]["duplicate_count"] == 1
    assert by_name["saga_v2"]["duplicate_bundles"] == ["Example Bundle"]
    assert by_name["saga_v2_again"]["review_status"] == "duplicate"
    assert by_name["saga_v2_again"]["duplicate_of"] == rows["saga_v2"].id
    # A copy discloses no set of its own — the chip belongs to the row that
    # represents the file.
    assert by_name["saga_v2_again"]["duplicate_count"] == 0

    # The Duplicates filter IS the review_status filter, and the pending view
    # excludes the copy exactly as it excludes an ignored row.
    parked = (
        await app_client.get(
            f"/api/v1/sources/{source_id}/entitlements?review_status=duplicate"
        )
    ).json()
    assert [row["machine_name"] for row in parked] == ["saga_v2_again"]
    pending = (
        await app_client.get(
            f"/api/v1/sources/{source_id}/entitlements?review_status=new"
        )
    ).json()
    assert [row["machine_name"] for row in pending] == ["saga_v2"]


@pytest.mark.req("FRG-SRC-004")
async def test_restore_through_the_surface_returns_a_copy_to_review(app_client):
    app = app_client.app
    db = app.state.db
    source_id = await _populate(
        app,
        [
            ("saga_v2", SAGA_SHORT, "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"),
            ("saga_v2_again", SAGA_SHORT, "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"),
        ],
    )
    rows = {r.machine_name: r for r in await repo.list_entitlements(db, source_id)}
    copy_id = rows["saga_v2_again"].id

    restored = (
        await app_client.post(f"/api/v1/sources/entitlements/{copy_id}/restore")
    ).json()

    assert restored["review_status"] == "new"
    assert restored["duplicate_of"] is None


@pytest.mark.req("FRG-SRC-004")
async def test_bulk_restore_covers_a_whole_duplicate_filter_selection(app_client):
    app = app_client.app
    db = app.state.db
    source_id = await _populate(
        app,
        [
            ("saga_v2", SAGA_SHORT, "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"),
            ("saga_v2_again", SAGA_SHORT, "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"),
            ("saga_v2_third", SAGA_SHORT, "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"),
        ],
    )
    parked = [
        row.id
        for row in await repo.list_entitlements(db, source_id, review_status="duplicate")
    ]
    assert len(parked) == 2

    resp = await app_client.post(
        "/api/v1/sources/entitlements/bulk",
        json={"action": "restore", "entitlement_ids": parked},
    )

    assert resp.status_code == 200
    assert resp.json()["applied"] == 2
    for eid in parked:
        row = await repo.get_entitlement(db, eid)
        assert row.review_status == "new"
        assert row.duplicate_of is None


@pytest.mark.req("FRG-SRC-015")
async def test_the_match_and_add_endpoints_refuse_a_parked_copy(app_client):
    """The direct row actions, not just accept: neither endpoint asks for the
    ``new`` precondition, so without an unconditional guard a POST straight at a
    parked copy resolved it — leaving it ``matched`` with ``duplicate_of`` still
    set and queueing the byte-identical grab the canonical already covers."""
    app = app_client.app
    db = app.state.db
    source_id = await _populate(
        app,
        [
            ("saga_v2", SAGA_SHORT, "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"),
            ("saga_v2_again", SAGA_SHORT, "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"),
        ],
    )
    rows = {r.machine_name: r for r in await repo.list_entitlements(db, source_id)}
    copy_id = rows["saga_v2_again"].id

    matched = await app_client.post(
        f"/api/v1/sources/entitlements/{copy_id}/match", json={"series_id": 1}
    )
    added = await app_client.post(
        f"/api/v1/sources/entitlements/{copy_id}/add", json={"cv_volume_id": 4242}
    )

    assert matched.status_code == 409
    assert added.status_code == 409
    assert "restore it first" in matched.text
    still_parked = await repo.get_entitlement(db, copy_id)
    assert still_parked.review_status == "duplicate"
    assert still_parked.duplicate_of == rows["saga_v2"].id


@pytest.mark.req("FRG-SRC-015")
async def test_an_ignored_canonical_stops_advertising_its_copies(app_client):
    """A withdrawn row represents nothing: the copies chip would invite the
    operator into a set whose representative they have already excluded."""
    app = app_client.app
    db = app.state.db
    source_id = await _populate(
        app,
        [
            ("saga_v2", SAGA_SHORT, "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"),
            ("saga_v2_again", SAGA_SHORT, "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"),
        ],
    )
    rows = {r.machine_name: r for r in await repo.list_entitlements(db, source_id)}
    canonical_id = rows["saga_v2"].id
    before = (await app_client.get(f"/api/v1/sources/{source_id}/entitlements")).json()
    assert {r["machine_name"]: r["duplicate_count"] for r in before}["saga_v2"] == 1

    ignored = (
        await app_client.post(f"/api/v1/sources/entitlements/{canonical_id}/ignore")
    ).json()
    # The action's OWN response is the row the client writes back into the list,
    # so it has to answer the copies question the same way the listing does.
    assert ignored["duplicate_count"] == 0

    listing = (
        await app_client.get(f"/api/v1/sources/{source_id}/entitlements")
    ).json()
    by_name = {row["machine_name"]: row for row in listing}
    assert by_name["saga_v2"]["review_status"] == "ignored"
    assert by_name["saga_v2"]["duplicate_count"] == 0
    assert by_name["saga_v2"]["duplicate_bundles"] == []
    # The single-row surface answers the same way.
    detail = (
        await app_client.get(f"/api/v1/sources/entitlements/{canonical_id}")
    ).json()
    assert detail["duplicate_count"] == 0

    # Back on the review surface, the same action response carries the chip
    # again — the copies are looked up per response, never assumed absent.
    restored = (
        await app_client.post(f"/api/v1/sources/entitlements/{canonical_id}/restore")
    ).json()
    assert restored["review_status"] == "new"
    assert restored["duplicate_count"] == 1
    assert restored["duplicate_bundles"] == ["Example Bundle"]
