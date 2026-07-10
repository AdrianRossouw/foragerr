# ddl-optin-seeding — design

## Context

FRG-DEP-013 (m2-first-run-defaults) seeds the GetComics indexer + built-in DDL
client **enabled** on first run so a keyless pipeline works out of the box. On
2026-07-09 a fresh demo install auto-grabbed live downloads from getcomics.org
within ~1 minute of a library import creating wanted issues — no operator
opt-in. With the repository public, first-boot outbound scraping is the wrong
default (surprise acquisition for new users; RISK-016 ToS exposure without
consent; undercuts the owned-library positioning).

## Goals / Non-Goals

**Goals**: seeded pair ships disabled; zero acquisition traffic before opt-in;
one-toggle activation; existing installs untouched; risk posture and manual
updated in the same change.

**Non-goals**: see proposal (no seed removal, no retroactive disable, no DDL
engine changes, no archive.org source).

## Decisions

1. **Seed disabled rather than not seeding.** Keeps the pipeline discoverable
   (rows visible in Settings with sane defaults) so activation is one toggle,
   and preserves all existing marker semantics (no-resurrection, no-injection)
   without a new mechanism. Alternative — dropping the seed entirely — loses
   discoverability and reopens the "which settings do I type in" first-run
   friction m2-first-run-defaults solved.
2. **Flip flags at the single seed site.** `backend/src/foragerr/db/first_run.py`
   passes `enabled=True` at two call sites; they become `enabled=False`, with
   the indexer's automatic-search/RSS usage toggles (FRG-IDX-002 fields) also
   off so a later single "enabled" click is still required for RSS/backlog
   participation (matching how a manually-added indexer behaves). No schema or
   migration change — the marker migration already exists.
3. **No retroactive disable.** Installs seeded enabled under the old posture
   keep their rows as-is (spec scenario pins this). A provider an operator may
   rely on must not silently stop working on upgrade.
4. **e2e spine enables explicitly.** The hermetic spine exercises grab→download
   via the seeded pair; it gains a visible setup step (API `PUT` enabling both
   rows) right after first-boot health, which doubles as e2e coverage of the
   one-toggle activation scenario.
5. **No-traffic scenario tested at the scheduler/search boundary.** The
   "no acquisition traffic before opt-in" scenario is asserted the same way
   existing disabled-indexer behavior is tested (disabled providers are
   excluded from search/RSS/backlog candidate sets) plus the existing
   hostile-network test fixtures — no new network-interception machinery.

## Risks / Trade-offs

- [First-run UX regresses: nothing downloads until a toggle] → deliberate; the
  manual's quick-start gains the enable step, and the Settings rows are
  pre-filled so it is one click, not a configuration task.
- [e2e spine forgets the enable step and goes red] → the step is part of this
  change's tasks and runs in the same gate.
- [Docs drift: manual still claims out-of-the-box downloads] → downloads.md
  passage is rewritten in this change; FRG-PROC-011 manual-sync gate applies.

## Migration Plan

No data migration. Fresh databases seed disabled from this change forward;
existing databases are untouched (marker already set, or marked-without-inject
per the unchanged established-install rule). Rollback = revert the commit.

## Open Questions

- None.
