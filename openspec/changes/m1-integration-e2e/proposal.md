# Change: m1-integration-e2e — Playwright end-to-end verification

## Why

Owner-requested addition to Phase 3 (2026-07-04): before Adrian reviews the completed
M1 slice, the system gets an automated once-over that drives the *real* application —
container, UI, API, OPDS — the way a user would, catching integration seams that
per-change unit/contract suites structurally cannot (frontend↔API drift, container
wiring, WS liveness, real-service handoffs).

## What Changes

- **Allocates one new requirement** (registered in
  `docs/traceability/requirements-registry.md` at proposal time per FRG-PROC-002):

  **FRG-PROC-010 — End-to-end slice verification harness.** The project SHALL
  maintain a browser-driven end-to-end suite (Playwright) that exercises the deployed
  application against its real container image with external services mocked by
  default and optionally live via env-gated credentials, covering at minimum: add a
  series (ComicVine fixture), interactive search showing rejection reasons, grab →
  download (fixture SAB/DDL; optionally a real SAB container with real news servers) →
  automatic import → renamed file in the library → series browse in the UI → OPDS
  feed navigation and file download with correct MIME. The suite SHALL run headless
  from one command, produce screenshots/traces on failure, and SHALL be green before
  a milestone is presented for owner review.

- **Delta spec**: `dev-process` gains the ADDED requirement above with scenarios.
- **Test infrastructure**: `e2e/` directory (Playwright + TS, its own package),
  compose file (foragerr image + fixture ComicVine/indexer/SAB services + optional
  real `linuxserver/sabnzbd` with Tweaknews/Newshosting creds from `.env`),
  fixture-data seeding, one `make e2e` / `npm run e2e` entrypoint.
- **Scope note**: runs after change 7 (needs the image + UI); authored now so the
  UI/OPDS implementation can keep its selectors/testability honest from the start
  (data-testid conventions documented here, consumed by change 7).
- **Acceptance layer (amended 2026-07-06 per the owner's 2026-07-05 decision,
  recorded in `docs/process/decisions.md`)**: this change's gate doubles as the M1
  UAT via a LIGHT acceptance layer — the acceptance report is **generated** from
  the FRG-tagged Playwright results (each e2e scenario names the requirement ids it
  exercises; the report maps scenario → tagged ids → pass/fail/skipped), with no
  hand-authored criteria matrix. The generated report is committed with the run
  (`e2e/acceptance-report.md`) and referenced from an `## Acceptance` section added
  to this proposal, where Adrian records his sign-off at his check-in. Merging the
  suite proceeds under the standing grant; the milestone is *acceptance-certified*
  when the sign-off line is filled.

## Capabilities

### New Capabilities

None (the requirement extends the existing `dev-process` capability).

### Modified Capabilities

- `dev-process`: ADDED FRG-PROC-010.

## Non-goals

- Not a replacement for per-requirement tagged tests (FRG-PROC-004) — this is the
  integration once-over, not requirement coverage.
- No performance/load testing (NFR-001/002/003 are M2 acceptance items).
- No visual-regression snapshots in M1 (candidate later; screenshots on failure only).
- No CI service — runs locally/sandbox via docker compose until a CI pipeline exists
  (FRG-PROC-007 note applies).

## Impact

- **New code**: `e2e/` (Playwright TS specs, fixtures, compose, seed scripts);
  `data-testid` conventions doc consumed by change 7's frontend work.
- **Registry**: FRG-PROC-010 allocated as `proposed` at commit time; flips
  `implemented` when the suite exists and runs green against the change-7 image.
- **Security**: no new attack surface (test-only tooling; creds stay env-gated and
  redacted).

## Manual impact

None (declared per FRG-PROC-011, which post-dates this proposal's original
approval): the e2e harness is development/verification tooling with no user- or
administrator-facing application behavior. The manual's deployment chapter already
documents the image the suite builds and drives; nothing it documents changes.

## Approval

- **Approver:** Adrian
- **Date:** 2026-07-04
- **Decision:** Approved under the standing grant of 2026-07-04 ("also maybe add
  another change to handle integration testing via playwright or similar, to give it
  a once-over before i take a look at it"). Implementation begins after change 7.
