"""One-time carry of per-source publisher rules into the library-wide list.

FRG-SRC-012 moved the non-comic publisher rules out of each source's encrypted
settings envelope and into a single library-wide setting
(``Settings.non_comic_publishers``). An install that already stored per-source
rules must not silently lose them, so on startup every source envelope is read
once, any stored entries are unioned into the library-wide value, and the
per-source field is cleared.

**Clearing is what makes the union one-time.** The hook runs on every boot; after
the first pass no source carries entries, so a re-run finds nothing to migrate
and an entry the operator later DELETES from the library-wide list is never
resurrected. There is no schema change and therefore no database or config-file
migration step — the pydantic default already answers a read of the absent key.

It runs as a startup hook rather than inside the config-file migration runner
because it needs the database AND the keystore: the rules live inside encrypted
envelopes, which the config path (running before either exists) cannot open.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from foragerr.config import (
    CONFIG_FILENAME,
    DEFAULT_NON_COMIC_PUBLISHERS,
    NON_COMIC_PUBLISHERS_ENV_VAR,
    apply_config_file_updates,
    env_var_is_set,
    read_config_file,
)
from foragerr.metadata.comicvine import split_csv
from foragerr.parser.normalize import matching_key
from foragerr.sources import repo

logger = logging.getLogger("foragerr.sources.publisher_migration")


def _rule_identity(entry: str) -> str:
    """The dedupe key for one rule entry: the shared fold the classifier matches
    on (FRG-IMP-005), so "Modiphius" and "modiphius entertainment." collapse the
    way they do at classification time rather than by a narrower ``casefold``.
    A punctuation-only entry folds to nothing and keeps its own spelling as the
    key, since it can never match a publisher and must not collapse with every
    other such entry.

    The trailing ``*`` is deliberately NOT part of the identity: a stored
    per-source "Paizo" and a default "Paizo*" are the same rule. Which SPELLING
    survives the collision is decided in :func:`union_publisher_rules`, which
    keeps the wildcard so the union never narrows a rule's reach."""
    return matching_key(entry) or entry.casefold()


def _flatten_commas(entry: str) -> str:
    """One per-source entry rewritten so it can survive the comma-separated
    library-wide list.

    Per-source rules were stored as JSON list items, where a comma inside one
    entry ("Wizards of the Coast, Inc*") is ordinary text. Joined into a CSV it
    would be re-split into fragments, and a fragment like "Inc*" is a substring
    probe that matches half the store. Commas become spaces instead, which the
    matching fold (FRG-IMP-005) already treats as equivalent — it folds
    punctuation to space — so the rule keeps matching exactly what it matched
    before, and a trailing ``*`` stays trailing."""
    return " ".join(entry.replace(",", " ").split())


def union_publisher_rules(current: str, additions: Iterable[str]) -> str:
    """The library-wide list with ``additions`` appended, deduped on the folded
    key. Entries already present keep their stored spelling and position, so a
    migration never reorders or rewrites what the operator can already see — the
    one exception being a collision where the addition is a wildcard and the
    stored entry is not: the wildcard replaces it in place, because dropping it
    would silently narrow a rule the operator had."""
    entries = split_csv(current)
    positions: dict[str, list[int]] = {}
    for index, entry in enumerate(entries):
        positions.setdefault(_rule_identity(entry), []).append(index)
    for addition in additions:
        entry = _flatten_commas(addition)
        if not entry:
            continue
        key = _rule_identity(entry)
        same = positions.get(key)
        if same is None:
            positions[key] = [len(entries)]
            entries.append(entry)
        elif entry.endswith("*") and not any(
            entries[index].endswith("*") for index in same
        ):
            entries[same[0]] = entry
    return ", ".join(entries)


async def _stored_rules(db) -> tuple[list[str], list[int]]:
    """Every per-source rule entry still stored in an envelope, plus the ids of
    the sources carrying them (row order, so the union is deterministic).

    A source whose envelope is blank or fails to decrypt contributes nothing and
    is left untouched: an undecryptable credential is a key problem, not a reason
    to abort the migration for every other source (FRG-AUTH-012 fail-soft)."""
    entries: list[str] = []
    source_ids: list[int] = []
    for row in await repo.list_sources(db):
        try:
            model = repo.load_source_settings(row.type, row.settings)
        except Exception:  # noqa: BLE001 — blank or undecryptable envelope
            logger.info(
                "publisher-rule migration: source %s has no readable settings; "
                "skipped (nothing migrated, nothing cleared)",
                row.id,
            )
            continue
        stored: list[str] = []
        for entry in getattr(model, "publisher_rules", None) or []:
            if not isinstance(entry, str) or not entry.strip():
                continue
            flattened = _flatten_commas(entry)
            if flattened != entry.strip():
                logger.info(
                    "publisher-rule migration: source %s rule %r carries commas, "
                    "which separate entries in the library-wide list; migrating "
                    "it as %r (same match, one rule)",
                    row.id,
                    entry,
                    flattened,
                )
            if flattened:
                stored.append(flattened)
        if not stored:
            continue
        entries.extend(stored)
        source_ids.append(row.id)
    return entries, source_ids


async def publisher_rules_migration_startup_hook(app) -> None:
    """Union stored per-source publisher rules into the library-wide list, then
    clear them (FRG-SRC-012, design D3).

    Never fatal: any failure is logged and the boot continues with the
    per-source entries still in place, so the next start retries a migration
    that is idempotent by construction."""
    db = getattr(app.state, "db", None)
    if db is None:  # pragma: no cover — the db area always runs first
        return
    try:
        await _migrate(app, db)
    except Exception:  # noqa: BLE001 — a stalled migration must not block boot
        logger.exception(
            "publisher-rule migration: failed; per-source rules are unchanged "
            "and the next start will retry"
        )


async def _migrate(app, db) -> None:
    entries, source_ids = await _stored_rules(db)
    if not source_ids:
        return

    if env_var_is_set(NON_COMIC_PUBLISHERS_ENV_VAR):
        # Writing the config file here would persist a value the environment
        # shadows on every read, so the union would look applied while having no
        # effect. Leave the per-source entries in place instead: unset the
        # variable and the next boot migrates them for real.
        logger.warning(
            "publisher-rule migration: %d source(s) still carry publisher rules "
            "that the classifier NO LONGER APPLIES — the non-comic publisher "
            "list is library-wide and currently managed by %s. The stored "
            "per-source rules are merged into the library-wide list on a start "
            "where that variable is unset; until then only the variable's value "
            "filters anything",
            len(source_ids),
            NON_COMIC_PUBLISHERS_ENV_VAR,
        )
        return

    settings = app.state.settings
    config_dir = Path(settings.config_dir)
    # The union bases on the value the config FILE carries, not on the possibly
    # stale in-memory settings: a restore-marker boot replaces config.yaml
    # underneath the loaded Settings, and merging into the stale value would
    # write the restored list back out of existence.
    stored = read_config_file(config_dir / CONFIG_FILENAME).get(
        "non_comic_publishers", DEFAULT_NON_COMIC_PUBLISHERS
    )
    current = stored if isinstance(stored, str) else ""
    merged = union_publisher_rules(current, entries)
    if merged != ", ".join(split_csv(current)):
        new_settings, _ = apply_config_file_updates(
            config_dir, {"non_comic_publishers": merged}
        )
        app.state.settings = new_settings
        # At startup the command service does not exist yet (this hook runs
        # ahead of the scheduler area, so no sync can be dispatched against the
        # pre-migration list at all). When one IS live, its HandlerContext holds
        # the settings workers read at execution time and has to be re-pointed.
        commands = getattr(app.state, "commands", None)
        if commands is not None:
            commands.context.settings = new_settings

    unclearable = 0
    for source_id in source_ids:
        if not await repo.clear_publisher_rules(db, source_id):
            unclearable += 1
    if unclearable:
        # An uncleared source still carries its entries, so the next start reads
        # them again — the union is idempotent, but the log must not claim a
        # finished migration.
        logger.warning(
            "publisher-rule migration: carried %d per-source rule(s) from %d "
            "source(s) into the library-wide non-comic publisher list, but %d "
            "source(s) could not be cleared and will be re-read at the next start",
            len(entries),
            len(source_ids),
            unclearable,
        )
        return
    logger.info(
        "publisher-rule migration: carried %d per-source rule(s) from %d "
        "source(s) into the library-wide non-comic publisher list",
        len(entries),
        len(source_ids),
    )


__all__ = ["publisher_rules_migration_startup_hook", "union_publisher_rules"]
