"""The library-wide non-comic publisher rules (FRG-SRC-012).

Format shape cannot tell a CBZ comic from a CBZ-shipped RPG sourcebook, so a
publisher rule list forces ``other`` whatever the formats say. The list is ONE
library-wide setting (``non_comic_publishers``) managed in Settings beside the
ComicVine ignore list — not a per-source control — it ships with a curated,
removable default set, matches on the shared folded key with a trailing ``*`` for
substring probes, and takes effect on the next sync, reclassifying only rows
still in the automatic classifier's hands.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml
from cryptography.fernet import Fernet, MultiFernet
from pydantic import ValidationError

from conftest import running_app
from foragerr import keystore as keystore_mod
from foragerr.config import (
    CONFIG_FILENAME,
    DEFAULT_NON_COMIC_PUBLISHERS,
    MAX_NON_COMIC_PUBLISHER_LENGTH,
    MAX_NON_COMIC_PUBLISHERS,
    NON_COMIC_PUBLISHERS_ENV_VAR,
    load_settings,
)
from foragerr.sources import commands as source_commands
from foragerr.sources import ratelimit, repo, review
from foragerr.sources.classify import DownloadOption, PublisherRuleSet, classify
from foragerr.sources.commands import SourceSyncCommand, _handle_source_sync
from foragerr.sources.models import MATCHED_VIA_OPERATOR
from foragerr.sources.publisher_migration import (
    publisher_rules_migration_startup_hook,
    union_publisher_rules,
)
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

#: A synthetic non-comic house used wherever the assertion is about the MATCHER
#: rather than about a shipped default.
OTHER_PUBLISHER = "Example Games"


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


def _opt(fmt: str, platform: str = "ebook") -> DownloadOption:
    return DownloadOption(
        format=fmt, platform=platform, md5=None, file_size=None, filename=None
    )


async def _source(db, *, name="Humble Bundle", publisher_rules=None):
    return await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name=name,
        settings=HumbleSettings(
            session_cookie="SYNTH-COOKIE", publisher_rules=publisher_rules or []
        ),
        connection_state="connected",
    )


def _sync_factory(config_dir):
    return make_factory(
        config_dir,
        httpx.MockTransport(
            order_handler(
                list_body=b'[{"gamekey":"%s"}]' % GAMEKEY.encode(),
                order_bodies={GAMEKEY: fixture_bytes("order_comics.json")},
            )
        ),
    )


async def _sync(db, config_dir, source, *, rules: str = ""):
    """One source synced with the library-wide list ``rules`` in force."""
    return await run_sync(
        db,
        _sync_factory(config_dir),
        source,
        min_interval=0.0,
        publisher_rules=PublisherRuleSet.from_csv(rules),
    )


async def _sync_every_source(db, config_dir, monkeypatch, *, rules: str):
    """Drive the REAL command handler, so the rules come from the effective
    settings rather than from a hand-built rule set."""
    factory = _sync_factory(config_dir)
    monkeypatch.setattr(source_commands, "make_humble_factory", lambda s: factory)
    ctx = SimpleNamespace(
        db=db,
        settings=make_settings(config_dir, non_comic_publishers=rules),
        commands=None,
    )
    return await _handle_source_sync(SourceSyncCommand(), ctx)


async def _classification(db, source_id: int, machine_name: str) -> str:
    rows = await repo.list_entitlements(db, source_id)
    return next(r for r in rows if r.machine_name == machine_name).classification


def _install_wrong_key() -> None:
    """A keystore whose key cannot decrypt anything encrypted so far — the
    wrong-key boot (FRG-AUTH-012), reused here to strand ONE source's envelope."""
    wrong = keystore_mod.derive_fernet_key("a-different-passphrase", b"0123456789abcdef")
    keystore_mod.install_keystore(
        keystore_mod.Keystore(MultiFernet([Fernet(wrong)]), available=False)
    )


# --- the matcher --------------------------------------------------------------


@pytest.mark.req("FRG-SRC-012")
def test_a_ruled_publisher_forces_other_over_every_format_signal():
    options = [_opt("CBZ"), _opt("PDF")]
    assert classify(options) == "comic"
    assert (
        classify(options, publisher=OTHER_PUBLISHER, publisher_rules=[OTHER_PUBLISHER])
        == "other"
    )


@pytest.mark.req("FRG-SRC-012")
def test_rule_matching_is_on_the_shared_folded_key():
    """Casing, punctuation, and article noise never decide a rule — the fold
    (FRG-IMP-005) does, so the operator types the publisher however they read
    it."""
    for spelling in (
        "example games",
        "EXAMPLE GAMES",
        "Example  Games.",
        "The Example Games",
    ):
        assert (
            classify(
                [_opt("CBZ")], publisher=spelling, publisher_rules=["Example Games"]
            )
            == "other"
        )


@pytest.mark.req("FRG-SRC-012")
def test_a_trailing_star_matches_as_a_substring_and_a_bare_name_matches_exactly():
    """The one reconciliation with the ComicVine ignore list's semantics
    (FRG-META-020): ``*`` widens a rule to a substring probe, everything else
    stays an exact folded match, so a bare name can never over-catch."""
    wide = ["Example Games*"]
    for publisher in ("Example Games", "Example Games Inc.", "The Example Games LLC"):
        assert classify([_opt("CBZ")], publisher=publisher, publisher_rules=wide) == "other"

    narrow = ["Example Games"]
    assert (
        classify([_opt("CBZ")], publisher="Example Games Inc.", publisher_rules=narrow)
        == "comic"
    )


@pytest.mark.req("FRG-SRC-012")
def test_the_wildcard_is_read_off_the_raw_entry_not_the_folded_key():
    """``matching_key`` folds ``*`` away as punctuation, so a probe derived from
    the folded string alone could never be told from an exact name — the
    substring rule has to be decided BEFORE the fold."""
    from foragerr.parser.normalize import matching_key

    assert matching_key("Example Games*") == matching_key("Example Games")
    compiled = PublisherRuleSet.parse(["Example Games*", "Example Press"])
    assert compiled.substrings == ("example games",)
    assert compiled.exact == frozenset({"example press"})


@pytest.mark.req("FRG-SRC-012")
def test_an_unmatched_or_absent_publisher_is_untouched():
    assert (
        classify([_opt("CBZ")], publisher="Image", publisher_rules=[OTHER_PUBLISHER])
        == "comic"
    )
    assert (
        classify([_opt("CBZ")], publisher=None, publisher_rules=[OTHER_PUBLISHER])
        == "comic"
    )
    # Blank/whitespace/punctuation-only entries fold away, and a bare "*" would
    # match every publisher, so it is dropped rather than honoured.
    for empty in (["", "  "], ["..."], ["*"], None):
        assert classify([_opt("CBZ")], publisher="Image", publisher_rules=empty) == "comic"
    assert not PublisherRuleSet.from_csv("")
    assert not PublisherRuleSet.from_csv(None)
    assert PublisherRuleSet.from_csv(DEFAULT_NON_COMIC_PUBLISHERS)


# --- the curated defaults -----------------------------------------------------


@pytest.mark.req("FRG-SRC-012")
def test_fresh_install_seeds_the_curated_non_comic_defaults(config_dir):
    """A fresh install renders its documented config.yaml with the curated
    default list, and the effective settings carry it — so a first sync files
    common non-comic bundle content as Other with no setup."""
    settings = load_settings()
    parsed = yaml.safe_load((config_dir / CONFIG_FILENAME).read_text(encoding="utf-8"))
    assert parsed["non_comic_publishers"] == DEFAULT_NON_COMIC_PUBLISHERS
    assert settings.non_comic_publishers == DEFAULT_NON_COMIC_PUBLISHERS
    # The default is a real, conservative list: wildcard entries are present, and
    # publishers of genuine comics are deliberately absent.
    assert "Paizo*" in DEFAULT_NON_COMIC_PUBLISHERS
    for comic_house in ("Image", "Dark Horse", "IDW", "Boom", "Oni", "Dynamite"):
        assert comic_house not in DEFAULT_NON_COMIC_PUBLISHERS


@pytest.mark.req("FRG-SRC-012")
def test_a_stored_non_comic_list_survives_upgrade(config_dir):
    """An upgraded install that already carries a value — including the empty
    string, meaning "filter nothing" — keeps it; the curated default seeds fresh
    installs only and never overwrites a stored value."""
    load_settings()  # first run seeds the documented default
    config_file = config_dir / CONFIG_FILENAME
    data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    data["non_comic_publishers"] = ""
    config_file.write_text(yaml.safe_dump(data), encoding="utf-8")

    assert load_settings().non_comic_publishers == ""


@pytest.mark.req("FRG-SRC-012")
def test_the_defaults_match_realistic_publisher_spellings():
    """Curation is only worth anything if the entries fire against the names the
    store actually reports — the ``*`` probes have to survive the fold, and the
    corporate suffixes a store attaches to a trading name ("Monte Cook Games,
    LLC") must not slip past a rule written for the house."""
    rules = PublisherRuleSet.from_csv(DEFAULT_NON_COMIC_PUBLISHERS)
    for publisher in (
        "Paizo Inc.",
        "Paizo Publishing",
        "Free League Publishing",
        "Green Ronin Publishing",
        "O'Reilly Media",
        "O’Reilly Media, Inc.",
        "No Starch Press",
        "Manning Publications Co.",
        "Addison-Wesley Professional",
        "John Wiley & Sons",
        "R. Talsorian Games",
        "The Pragmatic Bookshelf",
        "Mercury Learning and Information",
        "Steve Jackson Games",
        "Monte Cook Games, LLC",
        "Steve Jackson Games Incorporated",
        "Pelgrane Press Ltd",
        "Kobold Press LLC",
        "Apress L.P.",
        "Goodman Games LLC",
        "Pragmatic Bookshelf, LLC",
        "CRC Press LLC",
        "Renegade Game Studios, Inc.",
    ):
        assert rules.matches(publisher), publisher
    # Widening to substrings must not start catching comics houses. "Renegade
    # Game Studios*" is deliberately spelled in full: a bare "Renegade*" would
    # take Renegade Arts Entertainment, which publishes comics, with it.
    for comic_house in (
        "Image Comics",
        "Dark Horse Comics",
        "Renegade Arts Entertainment",
        "Oni Press",
        "Avery Hill Publishing",
        "Mad Cave Studios",
        COMIC_PUBLISHER,
    ):
        assert not rules.matches(comic_house), comic_house


# --- sync-time application + reclassification ---------------------------------


@pytest.mark.req("FRG-SRC-012")
async def test_an_empty_list_classifies_by_file_shape_alone(db, config_dir):
    source = await _source(db)
    result = await _sync(db, config_dir, source)
    assert (result.comic, result.other) == (3, 3)
    assert await _classification(db, source.id, "synth_singleissue_01") == "comic"


@pytest.mark.req("FRG-SRC-012")
async def test_a_library_wide_rule_reclassifies_new_rows_across_sources(
    db, config_dir, monkeypatch
):
    """ONE list, EVERY source: a publisher added to the library-wide list moves
    the still-new rows of both sources on the next sync — previously synced and
    newly synced alike."""
    first = await _source(db, name="Humble A")
    second = await _source(db, name="Humble B")
    await _sync_every_source(db, config_dir, monkeypatch, rules="")
    for source in (first, second):
        assert await _classification(db, source.id, "synth_singleissue_01") == "comic"

    await _sync_every_source(db, config_dir, monkeypatch, rules=COMIC_PUBLISHER)

    for source in (first, second):
        for machine_name in (
            "synth_singleissue_01",
            "synth_collected_edition_vol1",
            "synth_artbook_pdf_only",
        ):
            assert await _classification(db, source.id, machine_name) == "other"


@pytest.mark.req("FRG-SRC-012")
async def test_a_rule_naming_a_different_publisher_changes_nothing(db, config_dir):
    """Rules are matched on the publisher, not the format: a rule for the prose
    imprint leaves the comic imprint's items exactly where they were."""
    source = await _source(db)
    await _sync(db, config_dir, source)
    result = await _sync(db, config_dir, source, rules="Synthetic Press")
    assert await _classification(db, source.id, "synth_singleissue_01") == "comic"
    assert (result.comic, result.other) == (3, 3)


@pytest.mark.req("FRG-SRC-012")
async def test_a_rule_applies_at_first_sync_too(db, config_dir):
    source = await _source(db)
    result = await _sync(db, config_dir, source, rules=COMIC_PUBLISHER)
    assert await _classification(db, source.id, "synth_singleissue_01") == "other"
    assert (result.comic, result.other) == (0, 6)


@pytest.mark.req("FRG-SRC-012")
async def test_removing_a_default_unfilters_that_publisher_on_the_next_sync(
    db, config_dir
):
    """The safety valve: an operator who DOES collect one of the shipped houses
    deletes that entry and its items return to comic — nothing was destroyed, so
    the previously reclassified-but-unreviewed rows simply re-evaluate."""
    shipped = f"{DEFAULT_NON_COMIC_PUBLISHERS}, {COMIC_PUBLISHER}"
    source = await _source(db)
    await _sync(db, config_dir, source, rules=shipped)
    assert await _classification(db, source.id, "synth_singleissue_01") == "other"

    await _sync(db, config_dir, source, rules=DEFAULT_NON_COMIC_PUBLISHERS)
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

    await _sync(db, config_dir, source, rules=COMIC_PUBLISHER)

    assert await _classification(db, source.id, "synth_singleissue_01") == "comic"
    assert (
        await _classification(db, source.id, "synth_collected_edition_vol1") == "comic"
    )
    still = await repo.get_entitlement(db, matched.id)
    assert (still.review_status, still.matched_series_id) == ("matched", series_id)
    assert (await repo.get_entitlement(db, ignored.id)).review_status == "ignored"


@pytest.mark.req("FRG-SRC-012")
async def test_the_sync_reads_the_library_wide_list_not_the_source_envelope(
    db, config_dir, monkeypatch
):
    """The envelope field is storage compatibility only. A leftover per-source
    entry classifies NOTHING; the library-wide setting is the whole input."""
    source = await _source(db, publisher_rules=[COMIC_PUBLISHER])
    await _sync_every_source(db, config_dir, monkeypatch, rules="")
    assert await _classification(db, source.id, "synth_singleissue_01") == "comic"


# --- the one-time migration of per-source rules -------------------------------


def _app(db, settings):
    return SimpleNamespace(state=SimpleNamespace(db=db, settings=settings, commands=None))


def _stored_value(config_dir: Path) -> str:
    parsed = yaml.safe_load((config_dir / CONFIG_FILENAME).read_text(encoding="utf-8"))
    return parsed["non_comic_publishers"]


async def _rules_of(db, source_id: int) -> list[str]:
    row = await repo.get_source(db, source_id)
    return repo.load_source_settings(row.type, row.settings).publisher_rules


@pytest.mark.req("FRG-SRC-012")
def test_the_union_dedupes_on_the_folded_key_and_keeps_stored_spellings():
    """A per-source "Paizo" and the shipped "Paizo*" are ONE rule; keeping the
    entry already in the list preserves the broader wildcard reach."""
    merged = union_publisher_rules(
        "Paizo*, Example Press",
        ["paizo", "Example  Press.", "Example Games", "Example Games"],
    )
    assert merged == "Paizo*, Example Press, Example Games"
    assert union_publisher_rules("", ["Example Games"]) == "Example Games"
    assert union_publisher_rules("Example Games", []) == "Example Games"


@pytest.mark.req("FRG-SRC-012")
def test_the_union_keeps_the_wildcard_spelling_of_a_colliding_rule():
    """The collision is resolved in favour of REACH: a stored "Kobold Press*"
    that meets an exact "Kobold Press" replaces it in place rather than being
    dropped as a duplicate, which would silently narrow the operator's rule to
    houses spelled with no corporate suffix."""
    merged = union_publisher_rules("Kobold Press, Example Press", ["Kobold Press*"])
    assert merged == "Kobold Press*, Example Press"
    assert PublisherRuleSet.from_csv(merged).matches("Kobold Press LLC")
    # The reverse collision leaves the wider entry exactly as it was.
    assert (
        union_publisher_rules("Kobold Press*, Example Press", ["Kobold Press"])
        == "Kobold Press*, Example Press"
    )


@pytest.mark.req("FRG-SRC-012")
async def test_a_comma_bearing_per_source_rule_migrates_as_one_entry(db, config_dir):
    """Per-source rules were JSON list items, where a comma inside one entry is
    ordinary text. The library-wide list separates entries BY comma, so an entry
    carried across verbatim would be re-split into fragments — and a fragment
    like "Inc*" is a substring probe that matches half the store."""
    settings = load_settings()
    stored_rule = "Example Games, Inc*"
    source = await _source(db, publisher_rules=[stored_rule])

    await publisher_rules_migration_startup_hook(_app(db, settings))

    stored = _stored_value(config_dir)
    assert stored.endswith("Example Games Inc*")
    compiled = PublisherRuleSet.from_csv(stored)
    assert compiled.matches("Example Games, Inc.")
    assert "inc" not in compiled.substrings
    assert "inc" not in compiled.exact
    assert await _rules_of(db, source.id) == []


@pytest.mark.req("FRG-SRC-012")
async def test_per_source_rules_migrate_into_the_library_wide_list(db, config_dir):
    """The upgrade path: rules the operator already had per-source are carried
    into the single list and the per-source field is cleared."""
    settings = load_settings()
    first = await _source(db, name="Humble A", publisher_rules=[OTHER_PUBLISHER])
    second = await _source(db, name="Humble B", publisher_rules=["Example Press"])
    untouched = await _source(db, name="Humble C")

    await publisher_rules_migration_startup_hook(_app(db, settings))

    stored = _stored_value(config_dir)
    assert stored.startswith(DEFAULT_NON_COMIC_PUBLISHERS)
    assert stored.endswith(f"{OTHER_PUBLISHER}, Example Press")
    for source in (first, second, untouched):
        assert await _rules_of(db, source.id) == []


@pytest.mark.req("FRG-SRC-012")
async def test_the_migration_never_resurrects_an_entry_the_operator_removed(
    db, config_dir
):
    """Clearing the per-source field is what makes the union one-time: a second
    boot finds nothing to migrate, so an entry deleted in between stays deleted
    and the config file is not rewritten at all."""
    settings = load_settings()
    source = await _source(db, publisher_rules=[OTHER_PUBLISHER])
    app = _app(db, settings)
    await publisher_rules_migration_startup_hook(app)
    assert OTHER_PUBLISHER in _stored_value(config_dir)

    # The operator deletes the migrated entry through Settings...
    trimmed = make_settings(config_dir, non_comic_publishers="Example Press")
    app.state.settings = trimmed
    before = (config_dir / CONFIG_FILENAME).read_text(encoding="utf-8")

    await publisher_rules_migration_startup_hook(app)

    assert app.state.settings is trimmed  # no rewrite, no reload
    assert (config_dir / CONFIG_FILENAME).read_text(encoding="utf-8") == before
    assert await _rules_of(db, source.id) == []


@pytest.mark.req("FRG-SRC-012")
async def test_an_undecryptable_source_is_skipped_without_aborting_the_migration(
    db, config_dir
):
    """A stranded envelope contributes nothing and is left untouched — one
    unreadable credential must not cost every other source its rules."""
    settings = load_settings()
    stranded = await _source(db, name="Humble A", publisher_rules=["Example Press"])
    _install_wrong_key()
    readable = await _source(db, name="Humble B", publisher_rules=[OTHER_PUBLISHER])

    await publisher_rules_migration_startup_hook(_app(db, settings))

    stored = _stored_value(config_dir)
    assert OTHER_PUBLISHER in stored
    assert "Example Press" not in stored
    assert await _rules_of(db, readable.id) == []
    with pytest.raises(Exception):
        await _rules_of(db, stranded.id)


@pytest.mark.req("FRG-SRC-012")
async def test_the_migration_skips_the_union_when_the_env_var_manages_the_list(
    db, config_dir, monkeypatch, caplog
):
    """Writing the config file under an env-managed value would look applied and
    do nothing, so the migration leaves the per-source entries in place for a
    later boot instead of consuming them.

    The warning has to say what that costs: the kept entries are no longer
    applied by anything (the classifier reads the library-wide list only), so an
    operator who reads "still stored" as "still filtering" would be wrong."""
    settings = load_settings()
    source = await _source(db, publisher_rules=[OTHER_PUBLISHER])
    monkeypatch.setenv(NON_COMIC_PUBLISHERS_ENV_VAR, "Example Press")

    with caplog.at_level(
        logging.WARNING, logger="foragerr.sources.publisher_migration"
    ):
        await publisher_rules_migration_startup_hook(_app(db, settings))

    assert OTHER_PUBLISHER not in _stored_value(config_dir)
    assert await _rules_of(db, source.id) == [OTHER_PUBLISHER]
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "NO LONGER APPLIES" in logged
    assert NON_COMIC_PUBLISHERS_ENV_VAR in logged
    assert "unset" in logged


@pytest.mark.req("FRG-SRC-012")
async def test_the_union_bases_on_the_stored_config_not_the_loaded_settings(
    db, config_dir
):
    """A restore-marker boot replaces config.yaml underneath the Settings object
    already loaded from it, so the union has to read the FILE — merging into the
    stale in-memory value would write the restored list back out of existence."""
    stale = make_settings(config_dir, non_comic_publishers="Example Press")
    load_settings()  # renders config.yaml with the curated defaults
    source = await _source(db, publisher_rules=[OTHER_PUBLISHER])

    await publisher_rules_migration_startup_hook(_app(db, stale))

    stored = _stored_value(config_dir)
    assert stored.startswith(DEFAULT_NON_COMIC_PUBLISHERS)
    assert stored.endswith(OTHER_PUBLISHER)
    assert "Example Press" not in stored
    assert await _rules_of(db, source.id) == []


@pytest.mark.req("FRG-SRC-012")
async def test_an_already_listed_rule_clears_without_rewriting_the_config(
    db, config_dir
):
    """A per-source entry the library-wide list already carries adds nothing, so
    the file is left byte-for-byte alone — but the per-source field still has to
    be cleared, or every boot re-reads it."""
    settings = load_settings()
    source = await _source(db, publisher_rules=["Paizo"])
    before = (config_dir / CONFIG_FILENAME).read_text(encoding="utf-8")

    await publisher_rules_migration_startup_hook(_app(db, settings))

    assert (config_dir / CONFIG_FILENAME).read_text(encoding="utf-8") == before
    assert await _rules_of(db, source.id) == []


@pytest.mark.req("FRG-SRC-012")
async def test_a_failing_migration_is_logged_and_never_aborts_startup(
    db, config_dir, monkeypatch, caplog
):
    """Startup must survive a migration that cannot finish: the per-source rules
    stay put and the next boot retries, since replaying the union is idempotent."""
    settings = load_settings()
    source = await _source(db, publisher_rules=[OTHER_PUBLISHER])

    def _boom(*args, **kwargs):
        raise RuntimeError("config write failed")

    monkeypatch.setattr(
        "foragerr.sources.publisher_migration.apply_config_file_updates", _boom
    )
    with caplog.at_level(
        logging.ERROR, logger="foragerr.sources.publisher_migration"
    ):
        await publisher_rules_migration_startup_hook(_app(db, settings))

    assert any(record.exc_info for record in caplog.records)
    assert await _rules_of(db, source.id) == [OTHER_PUBLISHER]


@pytest.mark.req("FRG-SRC-012")
async def test_a_source_that_cannot_be_cleared_is_reported_as_unfinished(
    db, config_dir, monkeypatch, caplog
):
    """A source whose field survives the clear is re-read at the next start, so
    the completion log must not claim the migration is done."""
    settings = load_settings()
    await _source(db, publisher_rules=[OTHER_PUBLISHER])

    async def _no_write(db, source_id):
        return False

    monkeypatch.setattr(repo, "clear_publisher_rules", _no_write)
    with caplog.at_level(
        logging.WARNING, logger="foragerr.sources.publisher_migration"
    ):
        await publisher_rules_migration_startup_hook(_app(db, settings))

    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "could not be cleared" in logged


@pytest.mark.req("FRG-SRC-012")
async def test_the_startup_hook_runs_after_the_keystore_and_before_any_sync():
    """It reads encrypted envelopes, so it cannot run before the keystore hook
    installs the process key — and it must finish before the scheduler area
    starts the worker pools, which can dispatch a due source-sync at once. A
    sync that ran first would classify against the pre-migration list and, on an
    auto-sync source, auto-accept rows the operator's own rules ruled out."""
    from foragerr.keystore import keystore_startup_hook
    from foragerr.sources.publisher_migration import (
        publisher_rules_migration_startup_hook as hook,
    )

    cfg_hooks = _startup_hook_names()
    migration = cfg_hooks.index(_hook_name(hook))
    assert migration > cfg_hooks.index(_hook_name(keystore_startup_hook))
    # The scheduler area's own startup hook: it creates the command service,
    # starts the worker pools and starts the scheduler loop in one go, so a due
    # task can be dispatched the moment it returns.
    assert migration < cfg_hooks.index(
        "foragerr.commands:register_scheduler.<locals>._startup"
    )
    assert migration < cfg_hooks.index(
        "foragerr.app:create_app.<locals>._register_source_sync_task"
    )


def _hook_name(hook) -> str:
    """Module-qualified, because several areas register a startup hook that is
    locally named ``_startup``."""
    return f"{hook.__module__}:{hook.__qualname__}"


def _startup_hook_names() -> list[str]:
    import tempfile

    from foragerr.app import create_app

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "cfg"
        cfg.mkdir()
        app = create_app(make_settings(cfg, admin_username="a", admin_password="b" * 12))
        return [_hook_name(hook) for hook in app.state.startup_hooks]


# --- the Settings surface -----------------------------------------------------


@pytest.mark.req("FRG-SRC-012")
def test_the_stored_list_is_cleaned_and_bounded(config_dir):
    """Whatever route a value arrives by — the UI, a hand-edited config.yaml, a
    migration union — the stored list is trimmed, emptied of blanks, and freed of
    entries that duplicate a rule already in it. The wildcard is part of a rule's
    identity, so "Example Games" and "Example Games*" are two rules and both
    survive; two spellings of the SAME reach do not."""
    settings = make_settings(
        config_dir,
        non_comic_publishers=" Example Games ,, example  games. , Example Games*, ",
    )
    assert settings.non_comic_publishers == "Example Games, Example Games*"

    # Bounds exist so a pasted or corrupted value cannot make every sync compile
    # a pathological rule set; they sit far above any real list.
    with pytest.raises(ValidationError):
        make_settings(
            config_dir,
            non_comic_publishers="x" * (MAX_NON_COMIC_PUBLISHER_LENGTH + 1),
        )
    with pytest.raises(ValidationError):
        make_settings(
            config_dir,
            non_comic_publishers=", ".join(
                f"Example House {i}" for i in range(MAX_NON_COMIC_PUBLISHERS + 1)
            ),
        )


@pytest.fixture
async def app_client(tmp_path: Path):
    """One event loop for the app and the test (see ``conftest.running_app``):
    these tests mix HTTP calls with direct ``app.state.db`` awaits."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    async with running_app(make_settings(cfg)) as (_app, client):
        yield client


@pytest.mark.req("FRG-SRC-012")
async def test_the_general_resource_round_trips_the_non_comic_list(app_client):
    """The list is managed in Settings beside the ComicVine ignore list: echoed
    with its source on GET, written on PUT, and a removed default STAYS removed."""
    body = (await app_client.get("/api/v1/config/general")).json()
    assert body["non_comic_publishers"]["value"] == DEFAULT_NON_COMIC_PUBLISHERS
    assert body["non_comic_publishers"]["source"] in ("file", "default")

    kept = ", ".join(
        entry
        for entry in DEFAULT_NON_COMIC_PUBLISHERS.split(", ")
        if entry != "Paizo*"
    )
    resp = await app_client.put(
        "/api/v1/config/general", json={"non_comic_publishers": kept}
    )
    assert resp.status_code == 200
    assert resp.json()["non_comic_publishers"]["value"] == kept
    assert "Paizo*" not in (await app_client.get("/api/v1/config/general")).json()[
        "non_comic_publishers"
    ]["value"]
    # The two lists are independent axes — writing one leaves the other.
    assert resp.json()["comicvine_ignored_publishers"]["value"]

    cleared = await app_client.put(
        "/api/v1/config/general", json={"non_comic_publishers": ""}
    )
    assert cleared.json()["non_comic_publishers"]["value"] == ""


@pytest.mark.req("FRG-SRC-012")
async def test_an_env_managed_non_comic_list_is_read_only(app_client, monkeypatch):
    monkeypatch.setenv(NON_COMIC_PUBLISHERS_ENV_VAR, "Example Press")
    assert (await app_client.get("/api/v1/config/general")).json()[
        "non_comic_publishers"
    ]["source"] == "env"

    resp = await app_client.put(
        "/api/v1/config/general", json={"non_comic_publishers": "Example Games"}
    )
    assert resp.status_code == 409
    assert resp.json()["errors"][0]["field"] == "non_comic_publishers"


@pytest.mark.req("FRG-SRC-012")
async def test_the_sources_patch_no_longer_accepts_publisher_rules(app_client):
    """No per-source rule surface remains: the key is rejected outright, while
    the toggle that IS per-source still works."""
    app = app_client.app
    source = await _source(app.state.db)

    rejected = await app_client.patch(
        f"/api/v1/sources/{source.id}", json={"publisher_rules": ["Example Games"]}
    )
    assert rejected.status_code == 400  # extra="forbid", the uniform 4xx shape
    assert rejected.json()["errors"][0]["field"] == "publisher_rules"

    empty = await app_client.patch(f"/api/v1/sources/{source.id}", json={})
    assert empty.status_code == 400

    ok = await app_client.patch(
        f"/api/v1/sources/{source.id}", json={"auto_sync": True}
    )
    assert ok.status_code == 200
    assert ok.json()["auto_sync"] is True


@pytest.mark.req("FRG-SRC-012")
async def test_the_source_settings_form_renders_no_publisher_rules_field(app_client):
    """The field survives on the contract so an envelope written by an earlier
    release still deserializes, but it is hidden from the rendered form."""
    schema = (await app_client.get("/api/v1/sources/schema")).json()
    humble = next(s for s in schema if s["type"] == "humble")
    assert [f["name"] for f in humble["fields"]] == ["session_cookie"]
    assert humble["fields"][0]["order"] == 0
    # Still on the contract, and still validated when an old envelope carries it.
    model = HumbleSettings(session_cookie="c", publisher_rules=["  Example Games  "])
    assert model.publisher_rules == ["Example Games"]
    with pytest.raises(ValueError):
        HumbleSettings(
            session_cookie="c",
            publisher_rules=[f"pub-{i}" for i in range(MAX_PUBLISHER_RULES + 1)],
        )
