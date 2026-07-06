# Design: m1-integration-e2e

## Context

Runs against the change-7 Docker image — the real deployment artifact, not a dev
server. Fixture services make the default run hermetic; env-gated tiers switch in
real ComicVine and a real SABnzbd container with the operator's news servers
(`.env`: Tweaknews/Newshosting) for the full-fidelity pass Adrian sees before review.

## Goals / Non-Goals

**Goals:** one command produces a pass/fail verdict on the whole M1 slice with
failure traces; deterministic by default; real-service tier optional.

**Non-Goals:** requirement-level coverage (tagged suites own that), perf testing,
visual regression, CI wiring.

## Decisions

1. **Stack**: Playwright + TypeScript in `e2e/` with its own `package.json`
   (isolated from `frontend/`); `@playwright/test` runner; trace+screenshot on
   failure; single entry `npm run e2e` (wraps compose up → wait-healthy → test →
   compose down).

2. **Topology** (`e2e/compose.yaml`): `foragerr` (the built image, fresh /config
   volume per run) + `fixture-cv` (recorded ComicVine responses, static server) +
   `fixture-indexer` (Newznab XML fixtures incl. a rejection-rich result set) +
   `fixture-ddl` (recorded GetComics pages + downloadable test archive) +
   optional `sabnzbd` (real linuxserver image; profile-gated). foragerr's outbound
   base URLs point at fixtures via env config; egress `local-service` profiles for
   the compose network (exercises the real egress policy rather than bypassing it).

3. **Scenario spine** (one spec file per step, shared state via a seeded library):
   S1 first-run: container healthy, config generated, default profile seeded.
   S2 add series via UI (fixture CV), refresh command completes, issues listed.
   S3 interactive search overlay: rejected rows visible with verbatim reasons;
   approved row present in comparator order.
   S4 grab (DDL fixture) → queue shows progress → import completes → renamed file
   present in the library volume with the expected template name.
   S5 UI browse: library index (poster/table), series detail stats update.
   S6 OPDS: root → series → acquisition feed → file download asserting
   `application/vnd.comicbook+zip` MIME and byte-identity with the library file.
   S7 (profile `live-sab`): grab via real SABnzbd + real news servers, one small
   test NZB, through to import — skipped unless creds present.
   S8 restart resilience: `docker restart` mid-queue; queued state survives.

4. **Selector contract**: `data-testid` attributes namespaced `ft-*` (documented in
   `e2e/SELECTORS.md`, consumed by change 7's frontend); specs never select on CSS
   classes or text where a testid exists.

5. **Traceability**: specs' test names carry `FRG-PROC-010`; the suite maps steps
   to the requirement's scenarios 1:1. trace.py discovery: e2e specs live outside
   `frontend/src`, so FRG-PROC-010's tagged test is a thin
   `backend/tests/test_e2e_marker.py` asserting the e2e suite manifest exists and
   its scenario list covers the requirement (keeps the matrix honest without
   running Playwright in the unit lane) — plus the real evidence in the e2e run
   log attached to the milestone review.

## Risks / Trade-offs

- [Playwright flakiness] → testids + explicit waits on command status endpoints
  (not sleeps); retries=1 with trace capture.
- [Compose port collisions in sandbox] → ephemeral ports via compose port mapping
  0; suite reads assigned ports.
- [Live-SAB tier nondeterminism] → separate profile, never in the default gate;
  one small NZB; failures report but don't block the hermetic verdict.

## Migration Plan

Additive tooling only. Rollback = don't merge.

## Open Questions

None blocking.
