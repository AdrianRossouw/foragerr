# Change: m1-search-indexers — Newznab indexers and the decision engine

## Why

Phase 3 change 4 of 7 (approved plan, 2026-07-04). With a populated library
(change 3), foragerr must find releases: Newznab indexer support (DogNZB, NZB.su)
and the single decision engine every candidate release passes through — the most
load-bearing search machinery in the system, whose explainable accept/reject
contract also powers interactive search and, in change 5, the DDL provider.

## What Changes

Implements 25 approved baseline requirements (no new IDs; scenario elaboration only):

- **Indexers (FRG-IDX-001..010)** — provider-pattern `indexers` table with JSON
  settings validated per implementation; three independent toggles
  (RSS/auto/interactive) gating every fetch path; schema + live-test endpoints as the
  zero-frontend extensibility seam; `?t=caps` probe with caching; tiered
  cleaned-title `q=` query generation in category 7030 with zero-padding variants and
  a result cap; hardened RSS/XML parsing into normalized release records with typed
  `<error code>` mapping; per-indexer guid de-duplication and attribution stamping;
  per-indexer 2s rate limiting; usenet retention as `maxage` param and decision
  rejection; and the generic escalating back-off ladder (reused by DL/DDL in
  change 5).
- **Decision engine + search (FRG-SRCH-001..004, 006..010, 014)** — one ordered
  specification set producing Approved/TemporarilyRejected/Rejected with
  user-visible reasons and permanent/temporary types; the pinned pure-parser calling
  contract (parse failures are rejections, never exceptions); release-to-library
  mapping via clean titles + per-series aliases; the core specification inventory
  (format/upgrade/retention/queue/blocklist stubs where the backing store arrives in
  change 5 — spec'd inert, wired live there); search-match specifications (essential
  under q=-only searching); the prioritization comparator chain against the format
  profile; automatic search commands; scheduled backlog search with politeness
  delay; cross-indexer result de-duplication; and interactive search with the
  ~30-min cached grab.
- **Security & resilience (FRG-SEC-002 · FRG-NFR-005, 010)** — defusedxml-configured
  parsing for all indexer XML (DTD/external entities disabled, bounded expansion,
  hostile-fixture corpus); per-provider politeness with the persisted failure
  back-off ladder; workers never wedged by hostile/slow providers.
- **API (FRG-API-008, 009)** — `GET /release?issueId=` interactive search returning
  every decision including rejections-with-reasons, with server-side grab cache keyed
  indexerId+guid (~30 min, expiry → deterministic error, never silent re-search);
  provider `/schema` and `/test` endpoints driving 100%-dynamic settings forms.

## Capabilities

### New Capabilities

None — all requirements exist in the approved baseline specs.

### Modified Capabilities

- `idx`: FRG-IDX-001..010
- `srch`: FRG-SRCH-001..004, 006, 007, 008, 009, 010, 014
- `sec`: FRG-SEC-002
- `nfr`: FRG-NFR-005, FRG-NFR-010
- `api`: FRG-API-008, FRG-API-009

## Non-goals

- No grabbing/downloading: `POST /release` (grab) stores the cached candidate and
  enqueues a grab command that is **inert until change 5** wires download clients.
  Queue/blocklist specifications evaluate against empty stores until change 5.
- No RSS sync (FRG-SRCH-011, B) and no RSS-mode specifications (FRG-SRCH-005, B) —
  the RSS toggle ships schema-forward only.
- No Torznab (FRG-IDX-012, M2), no delay profiles / pending queue (FRG-SRCH-012/013,
  B), no preferred-term scoring or size bounds (FRG-QUAL-003/004, M2).
- No UI (change 7).

## Impact

- **New code**: `backend/src/foragerr/{indexers/, search/}`, API routers for
  release/provider endpoints, Alembic migration for indexers/back-off state/grab
  cache tables; tests with recorded Newznab fixtures (incl. hostile XML).
- **External services**: contract tests against fixtures only; live verification
  with Adrian's DogNZB/NZB.su keys happens manually at the change-5/7 gates.
- **Security**: new parser of untrusted input (indexer XML) → risk register rows
  RISK-024/035 (XXE/entity expansion) and RISK-027 (provider wedge) updated in this
  change; SEC-002 hostile corpus committed (FRG-PROC-006).
- **Registry**: on merge, the 25 rows flip `approved → implemented`.

## Approval

- **Approver:** Adrian
- **Date:** 2026-07-04
- **Decision:** Approved under the standing grant of 2026-07-04 covering changes
  3-7. Implementation may begin, scoped to the 25 requirements listed above.
