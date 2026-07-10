# ddl-optin-seeding — seeded DDL provider ships disabled

## Why

On 2026-07-09, a fresh demo install auto-grabbed two live downloads from
getcomics.org within about a minute of a library import creating wanted issues —
the operator never enabled anything. That is the default-enabled seeding posture
of m2-first-run-defaults (FRG-DEP-013) working exactly as specified, and the
incident shows the specification is wrong: with the repository now public
(going-public change), a first-run install that begins outbound scraping and
downloading on its own is the wrong default for new users, for getcomics.org
(RISK-016, ToS-sensitive scraping without consent), and for the project's
owned-library positioning. Acquisition should start with one deliberate toggle.

## What Changes

- **BREAKING (first-run behavior)**: first-run seeding still creates the
  GetComics indexer row and the built-in DDL client row — so the pipeline stays
  discoverable and pre-configured in Settings — but both rows are seeded
  **disabled** (`enabled=false`, and the indexer's automatic-search/RSS usage
  toggles off). No search, scrape, grab, or download happens until the operator
  enables them.
- Existing installs are untouched: the first-run marker semantics, the
  no-resurrection rule, and the no-injection-on-upgrade rule are unchanged.
- `docs/security/risk-register.md`: RISK-015 and RISK-016 posture returns from
  default-on to opt-in; the 2026-07-09 auto-grab incident is recorded as the
  triggering event.
- Manual: the downloads page's "fresh install ships with the pair already
  enabled" passage and any first-run/quick-start text change to "seeded
  disabled — enable in Settings to start acquiring", with the enable steps.
- Tests: seeding tests assert disabled rows; the e2e spine enables the seeded
  provider as an explicit, visible setup step before exercising grab→download.

## Non-goals

- No removal of the seed (rows still created; discoverability is the point of
  keeping them).
- No change to the DDL engine, allowlists, scraping politeness, or any other
  acquisition behavior once enabled.
- No archive.org / Digital Comic Museum source (separate idea, M4 candidate
  alongside the Humble Bundle importer).
- No migration for existing installs that already have the enabled seeded rows
  (they were operator-visible and deletable; retroactively disabling a
  provider an operator may rely on is worse than the disease).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `dep`: **FRG-DEP-013 — First-run default DDL provider seeding** changes from
  seeding enabled rows to seeding disabled rows; scenario set updated
  accordingly (fresh-install scenario asserts disabled; a new scenario pins
  "no outbound acquisition traffic before the operator enables").

## Impact

- **Code**: `backend/src/foragerr/db/first_run.py` (seed flags).
- **Tests**: `backend/tests/test_first_run_seeding.py` (+ any CRUD/API tests
  asserting the seeded rows' enabled state); `e2e/` spine setup gains an
  explicit enable step.
- **Docs**: `docs/manual/user/downloads.md` (default-on passage),
  `docs/manual/admin/configuration.md` (first-run description),
  `docs/security/risk-register.md` (RISK-015/016).
- **SOUP (FRG-PROC-012)**: none — no dependency changes.
- **Security (FRG-PROC-006)**: no new attack surface; default surface strictly
  shrinks (no outbound scraping until opt-in). Risk-register update in the same
  change.
- **Registry**: no new IDs — FRG-DEP-013 is modified in place.

## Approval

Approved by Adrian, 2026-07-09 ("approved"), seed-disabled variant as proposed.
