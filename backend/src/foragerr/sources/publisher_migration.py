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
    NON_COMIC_PUBLISHERS_ENV_VAR,
    apply_config_file_updates,
    env_var_is_set,
)
from foragerr.parser.normalize import matching_key
from foragerr.sources import repo
from foragerr.sources.classify import split_rules

logger = logging.getLogger("foragerr.sources.publisher_migration")


def _rule_identity(entry: str) -> str:
    """The dedupe key for one rule entry: the shared fold the classifier matches
    on (FRG-IMP-005), so "Modiphius" and "modiphius entertainment." collapse the
    way they do at classification time rather than by a narrower ``casefold``.
    A punctuation-only entry folds to nothing and keeps its own spelling as the
    key, since it can never match a publisher and must not collapse with every
    other such entry.

    The trailing ``*`` is deliberately NOT part of the identity: a stored
    per-source "Paizo" and a default "Paizo*" are the same rule, and keeping the
    entry already in the list preserves the broader wildcard reach."""
    return matching_key(entry) or entry.casefold()


def union_publisher_rules(current: str, additions: Iterable[str]) -> str:
    """The library-wide list with ``additions`` appended, deduped on the folded
    key. Entries already present keep their stored spelling and position, so a
    migration never reorders or rewrites what the operator can already see."""
    entries = split_rules(current)
    seen = {_rule_identity(entry) for entry in entries}
    for addition in additions:
        entry = addition.strip()
        if not entry:
            continue
        key = _rule_identity(entry)
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
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
        stored = [
            entry
            for entry in getattr(model, "publisher_rules", None) or []
            if isinstance(entry, str) and entry.strip()
        ]
        if not stored:
            continue
        entries.extend(stored)
        source_ids.append(row.id)
    return entries, source_ids


async def publisher_rules_migration_startup_hook(app) -> None:
    """Union stored per-source publisher rules into the library-wide list, then
    clear them (FRG-SRC-012, design D3)."""
    db = getattr(app.state, "db", None)
    if db is None:  # pragma: no cover — the db area always runs first
        return
    entries, source_ids = await _stored_rules(db)
    if not source_ids:
        return

    if env_var_is_set(NON_COMIC_PUBLISHERS_ENV_VAR):
        # Writing the config file here would persist a value the environment
        # shadows on every read, so the union would look applied while having no
        # effect. Leave the per-source entries in place instead: unset the
        # variable and the next boot migrates them for real.
        logger.warning(
            "publisher-rule migration: %d source(s) still carry publisher rules, "
            "but the non-comic publisher list is managed by %s; unset it to "
            "migrate them into the library-wide list",
            len(source_ids),
            NON_COMIC_PUBLISHERS_ENV_VAR,
        )
        return

    settings = app.state.settings
    merged = union_publisher_rules(settings.non_comic_publishers, entries)
    if merged != settings.non_comic_publishers:
        new_settings, _ = apply_config_file_updates(
            Path(settings.config_dir), {"non_comic_publishers": merged}
        )
        app.state.settings = new_settings
        # Command workers read settings off the service's HandlerContext at
        # execution time, so a sync started before the next restart would
        # otherwise classify against the pre-migration list.
        commands = getattr(app.state, "commands", None)
        if commands is not None:
            commands.context.settings = new_settings

    for source_id in source_ids:
        await repo.clear_publisher_rules(db, source_id)
    logger.info(
        "publisher-rule migration: carried %d per-source rule(s) from %d "
        "source(s) into the library-wide non-comic publisher list",
        len(entries),
        len(source_ids),
    )


__all__ = ["publisher_rules_migration_startup_hook", "union_publisher_rules"]
