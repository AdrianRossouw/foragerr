"""Operator-owned publisher classification rules (FRG-SRC-012, design D8).

Format shape cannot tell a CBZ comic from a CBZ-shipped RPG sourcebook, so the
operator owns a per-source list of publishers that force ``other``. The list
ships EMPTY, lives in the source's existing (encrypted) settings envelope,
matches on the shared folded key, and takes effect on the next sync —
reclassifying only rows still in the automatic classifier's hands.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from conftest import running_app
from foragerr.sources import ratelimit, repo, review
from foragerr.sources.classify import DownloadOption, classify
from foragerr.sources.models import MATCHED_VIA_OPERATOR
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.service import run_sync
from foragerr.sources.settings import MAX_PUBLISHER_RULES, HumbleSettings
from http_support import make_settings
from sources_support import (  # noqa: F401 — imported fixtures
    GAMEKEY,
    _comic,
    _mk_series,
    fixture_bytes,
    format_profile_id,
    make_factory,
    order_handler,
    root_folder_id,
)

#: The publisher the fixture's comics carry.
COMIC_PUBLISHER = "Synthetic Comics"


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


def _opt(fmt: str, platform: str = "ebook") -> DownloadOption:
    return DownloadOption(
        format=fmt, platform=platform, md5=None, file_size=None, filename=None
    )


async def _source(db, *, publisher_rules=None):
    return await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Humble Bundle",
        settings=HumbleSettings(
            session_cookie="SYNTH-COOKIE", publisher_rules=publisher_rules or []
        ),
        connection_state="connected",
    )


async def _set_rules(db, source_id: int, rules: list[str]):
    """Rewrite the source's rule list, then hand back the reloaded row (the sync
    reads its settings off the row it is given)."""
    row = await repo.get_source(db, source_id)
    await repo.update_source_settings(
        db,
        source_id,
        settings=HumbleSettings(
            session_cookie="SYNTH-COOKIE", publisher_rules=rules
        ),
        connection_state=row.connection_state,
    )
    return await repo.get_source(db, source_id)


async def _sync(db, config_dir, source):
    factory = make_factory(
        config_dir,
        httpx.MockTransport(
            order_handler(
                list_body=b'[{"gamekey":"%s"}]' % GAMEKEY.encode(),
                order_bodies={GAMEKEY: fixture_bytes("order_comics.json")},
            )
        ),
    )
    return await run_sync(db, factory, source, min_interval=0.0)


async def _classification(db, source_id: int, machine_name: str) -> str:
    rows = await repo.list_entitlements(db, source_id)
    return next(r for r in rows if r.machine_name == machine_name).classification


# --- the rule itself ---------------------------------------------------------


@pytest.mark.req("FRG-SRC-012")
def test_a_ruled_publisher_forces_other_over_every_format_signal():
    options = [_opt("CBZ"), _opt("PDF")]
    assert classify(options) == "comic"
    assert (
        classify(
            options, publisher="Modiphius", publisher_rules=["Modiphius"]
        )
        == "other"
    )


@pytest.mark.req("FRG-SRC-012")
def test_rule_matching_is_on_the_shared_folded_key():
    """Casing, punctuation, and article noise never decide a rule — the fold
    (FRG-IMP-005) does, so the operator types the publisher however they read
    it."""
    for spelling in (
        "modiphius entertainment",
        "MODIPHIUS ENTERTAINMENT",
        "Modiphius  Entertainment.",
        "The Modiphius Entertainment",
    ):
        assert (
            classify(
                [_opt("CBZ")],
                publisher=spelling,
                publisher_rules=["Modiphius Entertainment"],
            )
            == "other"
        )


@pytest.mark.req("FRG-SRC-012")
def test_an_unmatched_or_absent_publisher_is_untouched():
    assert (
        classify([_opt("CBZ")], publisher="Image", publisher_rules=["Modiphius"])
        == "comic"
    )
    assert (
        classify([_opt("CBZ")], publisher=None, publisher_rules=["Modiphius"])
        == "comic"
    )
    # Blank/whitespace rules fold away — an all-blank list is no rules at all.
    assert (
        classify([_opt("CBZ")], publisher="Image", publisher_rules=["", "  "])
        == "comic"
    )


@pytest.mark.req("FRG-SRC-012")
def test_rules_ship_empty_and_are_trimmed_deduped_and_bounded():
    assert HumbleSettings(session_cookie="c").publisher_rules == []
    settings = HumbleSettings(
        session_cookie="c",
        publisher_rules=["  Modiphius  ", "", "MODIPHIUS", "Chaosium"],
    )
    assert settings.publisher_rules == ["Modiphius", "Chaosium"]
    with pytest.raises(ValueError):
        HumbleSettings(
            session_cookie="c",
            publisher_rules=[f"pub-{i}" for i in range(MAX_PUBLISHER_RULES + 1)],
        )


@pytest.mark.req("FRG-SRC-012")
def test_rule_dedupe_uses_the_same_fold_the_classifier_matches_on():
    """Storage and matching must share ONE rule identity.

    De-duplication was ``str.casefold``, a strictly narrower equivalence than
    the classifier's ``matching_key``: these four spellings all match the same
    publisher at classify time, but three of them survived as separate stored
    rules — a list showing duplicates the operator cannot tell apart, where
    deleting one changes nothing.
    """
    spellings = [
        "Modiphius Entertainment",
        "modiphius entertainment",
        "Modiphius  Entertainment.",
        "The Modiphius Entertainment",
    ]
    settings = HumbleSettings(session_cookie="c", publisher_rules=spellings)
    assert settings.publisher_rules == ["Modiphius Entertainment"]
    # ...and every spelling still classifies the same way through that one rule.
    for spelling in spellings:
        assert (
            classify(
                [_opt("CBZ")],
                publisher=spelling,
                publisher_rules=settings.publisher_rules,
            )
            == "other"
        )


@pytest.mark.req("FRG-SRC-012")
def test_a_rule_that_folds_to_nothing_keeps_its_own_identity():
    """A punctuation-only rule can never match a publisher (``matching_key``
    folds it away), so it must not collapse with every other such entry into a
    single empty key."""
    settings = HumbleSettings(session_cookie="c", publisher_rules=["...", "???"])
    assert settings.publisher_rules == ["...", "???"]


# --- sync-time application + reclassification -------------------------------


@pytest.mark.req("FRG-SRC-012")
async def test_default_source_classifies_exactly_as_before(db, config_dir):
    """Empty by default: no rule is pre-applied, so the format-shape verdict
    stands untouched (no intent-presuming defaults)."""
    source = await _source(db)
    result = await _sync(db, config_dir, source)
    assert (result.comic, result.other) == (3, 3)
    assert await _classification(db, source.id, "synth_singleissue_01") == "comic"


@pytest.mark.req("FRG-SRC-012")
async def test_a_new_rule_reclassifies_unreviewed_rows_on_the_next_sync(
    db, config_dir
):
    """Rule added AFTER the items were synced: the next sync moves the still-new
    ones comic → other (previously synced and newly synced alike)."""
    source = await _source(db)
    await _sync(db, config_dir, source)
    assert await _classification(db, source.id, "synth_singleissue_01") == "comic"

    source = await _set_rules(db, source.id, [COMIC_PUBLISHER])
    result = await _sync(db, config_dir, source)

    # Every item of that publisher moves, whatever its format shape said.
    for machine_name in (
        "synth_singleissue_01",
        "synth_collected_edition_vol1",
        "synth_artbook_pdf_only",
    ):
        assert await _classification(db, source.id, machine_name) == "other"
    assert (result.comic, result.other) == (0, 6)  # counters report the rows


@pytest.mark.req("FRG-SRC-012")
async def test_a_rule_naming_a_different_publisher_changes_nothing(db, config_dir):
    """Rules are matched on the publisher, not the format: a rule for the prose
    imprint leaves the comic imprint's items exactly where they were."""
    source = await _source(db)
    await _sync(db, config_dir, source)
    source = await _set_rules(db, source.id, ["Synthetic Press"])
    result = await _sync(db, config_dir, source)
    assert await _classification(db, source.id, "synth_singleissue_01") == "comic"
    assert (result.comic, result.other) == (3, 3)


@pytest.mark.req("FRG-SRC-012")
async def test_a_rule_applies_at_first_sync_too(db, config_dir):
    source = await _source(db, publisher_rules=[COMIC_PUBLISHER])
    result = await _sync(db, config_dir, source)
    assert await _classification(db, source.id, "synth_singleissue_01") == "other"
    assert (result.comic, result.other) == (0, 6)


@pytest.mark.req("FRG-SRC-012")
async def test_removing_a_rule_reclassifies_back_on_the_next_sync(db, config_dir):
    """The other direction — a rule the operator regrets is undone by deleting
    it; nothing was destroyed, so the row simply returns to comic."""
    source = await _source(db, publisher_rules=[COMIC_PUBLISHER])
    await _sync(db, config_dir, source)
    assert await _classification(db, source.id, "synth_singleissue_01") == "other"

    source = await _set_rules(db, source.id, [])
    await _sync(db, config_dir, source)
    assert await _classification(db, source.id, "synth_singleissue_01") == "comic"


@pytest.mark.req("FRG-SRC-012")
async def test_decided_rows_are_never_reclassified(
    db, config_dir, root_folder_id, format_profile_id
):
    """A matched or ignored row is an operator decision: a later rule edit must
    not move it between the review buckets it was decided in."""
    source = await _source(db)
    await _sync(db, config_dir, source)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7300, title="Synthetic Hero"
    )
    matched = await _comic(db, source.id, "synth_singleissue_01")
    ignored = await _comic(db, source.id, "synth_collected_edition_vol1")
    await review.match_entitlement(
        db,
        matched.id,
        series_id=series_id,
        commands=None,
        matched_via=MATCHED_VIA_OPERATOR,
    )
    await review.ignore_entitlement(db, ignored.id)

    source = await _set_rules(db, source.id, [COMIC_PUBLISHER])
    await _sync(db, config_dir, source)

    assert await _classification(db, source.id, "synth_singleissue_01") == "comic"
    assert (
        await _classification(db, source.id, "synth_collected_edition_vol1")
        == "comic"
    )
    still = await repo.get_entitlement(db, matched.id)
    assert (still.review_status, still.matched_series_id) == ("matched", series_id)
    assert (await repo.get_entitlement(db, ignored.id)).review_status == "ignored"


# --- the settings surface ----------------------------------------------------


@pytest.fixture
async def app_client(tmp_path: Path):
    """One event loop for the app and the test (see ``conftest.running_app``):
    these tests mix HTTP calls with direct ``app.state.db`` awaits."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    async with running_app(make_settings(cfg)) as (_app, client):
        yield client


@pytest.mark.req("FRG-SRC-012")
async def test_patch_publisher_rules_round_trips_without_echoing_the_cookie(
    app_client,
):
    """The rules ride the existing settings envelope: PATCH replaces the whole
    list, GET reflects it, and the write-only cookie survives the rewrite
    without ever being echoed (FRG-SRC-002)."""
    app = app_client.app
    source = await _source(app.state.db)

    listed_before = (await app_client.get("/api/v1/sources")).json()[0]
    assert listed_before["settings"]["publisher_rules"] == []

    resp = await app_client.patch(
        f"/api/v1/sources/{source.id}",
        json={"publisher_rules": ["Modiphius", "  Chaosium  ", "MODIPHIUS"]},
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["publisher_rules"] == ["Modiphius", "Chaosium"]
    assert "session_cookie" not in resp.json()["settings"]

    listed = (await app_client.get("/api/v1/sources")).json()[0]
    assert listed["settings"]["publisher_rules"] == ["Modiphius", "Chaosium"]
    # The credential still loads and still decrypts after the rewrite.
    row = await repo.get_source(app.state.db, source.id)
    model = repo.load_source_settings(row.type, row.settings)
    assert model.session_cookie.get_secret_value() == "SYNTH-COOKIE"

    cleared = await app_client.patch(
        f"/api/v1/sources/{source.id}", json={"publisher_rules": []}
    )
    assert cleared.json()["settings"]["publisher_rules"] == []


@pytest.mark.req("FRG-SRC-012")
async def test_patch_can_set_rules_and_auto_sync_in_one_body(app_client):
    app = app_client.app
    source = await _source(app.state.db)
    resp = await app_client.patch(
        f"/api/v1/sources/{source.id}",
        json={"auto_sync": True, "publisher_rules": ["Modiphius"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auto_sync"] is True
    assert body["settings"]["publisher_rules"] == ["Modiphius"]


@pytest.mark.req("FRG-SRC-012")
async def test_patch_rules_on_a_source_with_no_settings_envelope_is_a_409(
    app_client,
):
    """A disconnected source's credential is deliberately deleted, so there is
    no envelope to write into — a 409 that names the fix, never a settings row
    silently minted without a cookie."""
    app = app_client.app
    source = await _source(app.state.db)
    await app_client.post(f"/api/v1/sources/{source.id}/disconnect")

    resp = await app_client.patch(
        f"/api/v1/sources/{source.id}", json={"publisher_rules": ["Modiphius"]}
    )
    assert resp.status_code == 409
    assert resp.json()["errors"][0]["field"] == "publisher_rules"


@pytest.mark.req("FRG-SRC-012")
async def test_a_rules_write_never_resurrects_a_deleted_credential(app_client):
    """The verified credential-resurrection race.

    The write used to be a read-modify-write across THREE transactions
    (``get_source`` → decrypt in Python → ``update_source_settings``), and it
    passed ``connection_state`` forward from the stale first read. A
    ``disconnect`` committing in the middle — blanking the settings JSON and
    setting ``disconnected`` — was then overwritten by the trailing write, which
    re-persisted the decrypted-then-re-encrypted cookie the operator had just
    deleted AND restored the ``connected`` state with it.

    Simulated deterministically by racing the disconnect against the repo call:
    the write must find a blank envelope and refuse (409), never rebuild one.
    """
    app = app_client.app
    db = app.state.db
    source = await _source(db)

    # The disconnect commits first (the losing interleaving of the race).
    await app_client.post(f"/api/v1/sources/{source.id}/disconnect")

    resp = await app_client.patch(
        f"/api/v1/sources/{source.id}", json={"publisher_rules": ["Modiphius"]}
    )
    assert resp.status_code == 409

    row = await repo.get_source(db, source.id)
    assert row.connection_state == "disconnected"  # never flipped back
    assert row.settings == "{}"  # the credential stays deleted
    with pytest.raises(Exception):
        repo.load_source_settings(row.type, row.settings)


@pytest.mark.req("FRG-SRC-012")
async def test_the_rules_write_is_one_transaction_and_never_writes_state(db):
    """The repo seam the API now delegates to: read → validate → merge →
    serialize inside ONE ``write_session``, and ``connection_state`` is not a
    parameter of it at all — a rules edit can no longer reconnect anything.

    Proven on an ``expired`` source: the rules land and the state is preserved
    rather than rewritten to whatever a stale read held."""
    source = await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Humble Bundle",
        settings=HumbleSettings(session_cookie="SYNTH-COOKIE"),
        connection_state="expired",
    )
    written = await repo.update_publisher_rules(db, source.id, ["Modiphius"])
    assert written.connection_state == "expired"
    model = repo.load_source_settings(written.type, written.settings)
    assert model.publisher_rules == ["Modiphius"]
    assert model.session_cookie.get_secret_value() == "SYNTH-COOKIE"

    assert await repo.update_publisher_rules(db, 999999, []) is None

    await repo.set_connection_state(
        db, source.id, "disconnected", clear_credential=True
    )
    with pytest.raises(repo.SourceSettingsUnavailable):
        await repo.update_publisher_rules(db, source.id, ["Modiphius"])


@pytest.mark.req("FRG-SRC-012")
async def test_connect_accepts_publisher_rules_in_the_settings_body(
    app_client, tmp_path: Path
):
    """The rule list is part of the store type's settings contract, so it is
    settable at connect time too (and renders from the schema)."""
    app = app_client.app
    app.state.http_factory = make_factory(
        app.state.settings.config_dir,
        httpx.MockTransport(
            order_handler(list_body=fixture_bytes("order_list.json"))
        ),
    )
    resp = await app_client.post(
        "/api/v1/sources",
        json={
            "type": "humble",
            "settings": {
                "session_cookie": "COOKIE",
                "publisher_rules": ["Modiphius"],
            },
        },
    )
    assert resp.status_code == 201
    assert resp.json()["source"]["settings"]["publisher_rules"] == ["Modiphius"]

    schema = (await app_client.get("/api/v1/sources/schema")).json()
    humble = next(s for s in schema if s["type"] == "humble")
    field = next(f for f in humble["fields"] if f["name"] == "publisher_rules")
    assert field["required"] is False
    assert field["secret"] is False
