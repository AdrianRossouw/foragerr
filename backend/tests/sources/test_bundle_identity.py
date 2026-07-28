"""Bundle identity on every review row (FRG-SRC-011, design D4).

``product.human_name`` has been in every Humble order payload since M6 and was
parsed away; it is now captured at sync, denormalized per entitlement,
backfilled onto pre-0026 rows by the next sync, and exposed on the review
resource alongside the SHARED collapse fold ``group_key``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from conftest import running_app
from foragerr.api.sources import _group_key
from foragerr.parser.normalize import matching_key
from foragerr.sources import ratelimit, repo
from foragerr.sources.humble import parse_order
from foragerr.sources.matching import query_term
from foragerr.sources.models import SourceEntitlementRow
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.service import run_sync
from foragerr.sources.settings import HumbleSettings
from http_support import make_settings
from sources_support import (  # noqa: F401 — imported fixtures
    GAMEKEY,
    _comic,
    _synced_source,
    fixture_bytes,
    make_factory,
    order_handler,
)

BUNDLE = "Synthetic Comics Bundle"


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


# --- parse ------------------------------------------------------------------


@pytest.mark.req("FRG-SRC-011")
def test_parse_order_carries_the_bundle_name_onto_every_item():
    parsed = parse_order(GAMEKEY, fixture_bytes("order_comics.json"))
    assert parsed  # the fixture yields items
    assert {p.bundle_human_name for p in parsed} == {BUNDLE}


@pytest.mark.req("FRG-SRC-011")
def test_an_order_without_a_product_object_parses_with_a_null_bundle_name():
    """A bundle name is nice-to-have metadata: an order that carries no
    ``product`` (or an unusable one) must still parse, with NULL — never a
    skipped order."""
    body = json.dumps(
        {
            "subproducts": [
                {
                    "machine_name": "x1",
                    "human_name": "Nameless Bundle Item",
                    "downloads": [
                        {
                            "platform": "ebook",
                            "download_struct": [{"name": "CBZ"}],
                        }
                    ],
                }
            ]
        }
    ).encode()
    parsed = parse_order("gk", body)
    assert [p.bundle_human_name for p in parsed] == [None]

    # A product that is not an object, and one whose name sanitizes away.
    for product in ("a string", {"human_name": "   "}, {"human_name": None}):
        body = json.dumps(
            {"product": product, "subproducts": [{"machine_name": "x1"}]}
        ).encode()
        assert parse_order("gk", body)[0].bundle_human_name is None


@pytest.mark.req("FRG-SRC-011")
def test_a_hostile_bundle_name_is_sanitized_like_any_store_string():
    """The bundle name is untrusted store input (FRG-NFR-012 / FRG-META-014):
    it rides the same sanitizer as the title, so markup and control characters
    never reach the row."""
    body = json.dumps(
        {
            "product": {"human_name": "<script>alert(1)</script>Evil​ Bundle"},
            "subproducts": [{"machine_name": "x1"}],
        }
    ).encode()
    name = parse_order("gk", body)[0].bundle_human_name
    assert name is not None
    assert "<script>" not in name
    assert "​" not in name


# --- sync persistence + backfill --------------------------------------------


@pytest.mark.req("FRG-SRC-011")
async def test_sync_persists_the_bundle_name_on_every_row(db, config_dir):
    source = await _synced_source(db, config_dir)
    rows = await repo.list_entitlements(db, source.id)
    assert rows
    assert {r.bundle_human_name for r in rows} == {BUNDLE}


@pytest.mark.req("FRG-SRC-011")
async def test_resync_backfills_the_bundle_name_on_pre_migration_rows(
    db, config_dir
):
    """Migration 0026 rewrites no data: an existing row carries NULL until its
    next sync refreshes it, exactly like any other display detail
    (FRG-SRC-003's safe-resync rule)."""
    source = await _synced_source(db, config_dir)
    # Simulate the pre-0026 shape: rows exist, the column is NULL.
    async with db.write_session() as session:
        for row in (
            (await session.execute(select(SourceEntitlementRow))).scalars().all()
        ):
            row.bundle_human_name = None
    assert all(
        r.bundle_human_name is None for r in await repo.list_entitlements(db, source.id)
    )

    factory = make_factory(
        config_dir,
        httpx.MockTransport(
            order_handler(
                list_body=b'[{"gamekey":"%s"}]' % GAMEKEY.encode(),
                order_bodies={GAMEKEY: fixture_bytes("order_comics.json")},
            )
        ),
    )
    result = await run_sync(db, factory, source, min_interval=0.0)

    assert result.new_entitlements == 0  # a backfill, not a re-discovery
    assert {
        r.bundle_human_name for r in await repo.list_entitlements(db, source.id)
    } == {BUNDLE}


@pytest.mark.req("FRG-SRC-011")
async def test_a_payload_without_a_bundle_name_never_nulls_a_captured_one(
    db, config_dir
):
    """The backfill is FORWARD-only.

    Humble's order shapes vary (the ``product`` object is not always present —
    see ``test_an_order_without_a_product_object_parses_with_a_null_bundle_name``),
    and the refresh assigned the parsed value unconditionally. So a single such
    response silently emptied the name on every row of that order, taking the
    "select whole bundle" affordance with it — and the next well-formed sync was
    the only way back. An absent name is not evidence that the row has none.
    """
    source = await _synced_source(db, config_dir)
    assert {
        r.bundle_human_name for r in await repo.list_entitlements(db, source.id)
    } == {BUNDLE}

    # The same order, re-served with its bundle-naming ``product`` object gone.
    import json

    payload = json.loads(fixture_bytes("order_comics.json"))
    payload.pop("product", None)
    factory = make_factory(
        config_dir,
        httpx.MockTransport(
            order_handler(
                list_body=b'[{"gamekey":"%s"}]' % GAMEKEY.encode(),
                order_bodies={GAMEKEY: json.dumps(payload).encode()},
            )
        ),
    )
    result = await run_sync(db, factory, source, min_interval=0.0)

    assert result.new_entitlements == 0
    assert {
        r.bundle_human_name for r in await repo.list_entitlements(db, source.id)
    } == {BUNDLE}


# --- the review resource ----------------------------------------------------


@pytest.mark.req("FRG-SRC-011")
def test_group_key_is_the_stripped_fold_of_the_series_shaped_term():
    """``group_key`` must be ``stripped_key(query_term(...))`` and nothing else
    — a second, drifting fold on the client is exactly what computing it
    server-side prevents. STRIPPED, not plain: store idioms like
    "EMBER Vol. 243" keep their ordinal through the plain fold, splintering
    a large same-title run into one group per ordinal."""
    from foragerr.sources.matching import stripped_key

    title = "Synthetic Hero #1"
    assert _group_key(title) == stripped_key(query_term(title))
    assert _group_key(title) == "synthetic hero"
    # Edition slices of one title share the group.
    assert (
        _group_key("EMBER Vol. 243")
        == _group_key("Ember Issues #8")
        == _group_key("Ember #211")
        == "ember"
    )


@pytest.mark.req("FRG-SRC-011")
def test_same_series_rows_share_a_group_key_across_issue_and_copy_noise():
    """A large same-title run with per-ordinal idioms: per-copy suffixes fold
    away, so the whole run collapses into ONE group."""
    keys = {
        _group_key("Ember #1"),
        _group_key("Ember #211"),
        _group_key("ember"),
        _group_key("The Ember (digital edition)"),
    }
    assert len(keys) == 1


@pytest.mark.req("FRG-SRC-011")
def test_group_key_of_an_unfoldable_title_is_empty_not_an_error():
    assert _group_key("###") == ""


@pytest.mark.req("FRG-SRC-011")
async def test_the_wire_group_key_is_always_a_string_never_null(
    db, config_dir, tmp_path: Path
):
    """The ungroupable signal is ``""``, on the wire, deliberately — DECIDED
    rather than left implicit: absence and emptiness must not diverge on
    the wire when the client's rule is "'' never groups".

    Emitting ``null``/omitting the field for an unfoldable title would re-key
    the client's rule off ABSENCE; the client already implements exactly the
    same behaviour off the empty string ("``''`` never groups"), so changing the
    wire type buys nothing and breaks its typing. This pins the decision so a
    later "tidy-up" to ``str | None`` fails here rather than in the UI: the
    field is present, is a ``str``, and is ``""`` for a title that folds away.
    """
    from foragerr.api.sources import EntitlementResource

    source = await _synced_source(db, config_dir)
    rows = await repo.list_entitlements(db, source.id)
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, rows[0].id)
        row.human_name = "###"
    reloaded = await repo.get_entitlement(db, rows[0].id)

    payload = EntitlementResource.from_row(reloaded).model_dump()
    assert "group_key" in payload
    assert payload["group_key"] == ""
    assert isinstance(payload["group_key"], str)


@pytest.mark.req("FRG-SRC-011")
async def test_entitlement_resource_exposes_bundle_name_and_group_key(
    tmp_path: Path,
):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    # One event loop for the app and the test (see ``conftest.running_app``):
    # this test mixes HTTP calls with direct ``app.state.db`` awaits.
    async with running_app(make_settings(cfg)) as (app, client):
        source = await repo.create_source(
            app.state.db,
            source_type=TYPE_HUMBLE,
            name="Humble Bundle",
            settings=HumbleSettings(session_cookie="SYNTH-COOKIE"),
            connection_state="connected",
        )
        factory = make_factory(
            app.state.settings.config_dir,
            httpx.MockTransport(
                order_handler(
                    list_body=b'[{"gamekey":"%s"}]' % GAMEKEY.encode(),
                    order_bodies={GAMEKEY: fixture_bytes("order_comics.json")},
                )
            ),
        )
        await run_sync(app.state.db, factory, source, min_interval=0.0)

        listed = (
            await client.get(
                f"/api/v1/sources/{source.id}/entitlements?classification=comic"
            )
        ).json()
        assert listed
        assert {row["bundle_human_name"] for row in listed} == {BUNDLE}
        single = next(
            r for r in listed if r["machine_name"] == "synth_singleissue_01"
        )
        assert single["group_key"] == "synthetic hero"

        detail = (
            await client.get(f"/api/v1/sources/entitlements/{single['id']}")
        ).json()
        assert detail["bundle_human_name"] == BUNDLE
        assert detail["group_key"] == "synthetic hero"
