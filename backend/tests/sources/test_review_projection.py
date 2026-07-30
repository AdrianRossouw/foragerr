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
def test_the_display_merge_is_order_independent_and_transitively_closed():
    chain = ["alpha", "alpha beta", "gamma alpha beta"]
    forward = merge_display_groups(chain)
    reverse = merge_display_groups(list(reversed(chain)))

    assert forward == reverse
    # "alpha" is not inside "gamma alpha beta" as a pairwise SHORTEST match only
    # via the middle link — the component must still close over the chain.
    assert set(forward.values()) == {"alpha"}


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
