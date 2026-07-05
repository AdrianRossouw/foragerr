# Change: m1-downloads — SABnzbd and DDL acquisition

## Why

Phase 3 change 5 of 7 (approved plan, 2026-07-04). Change 4 finds and approves
releases; this change acquires them: the download-client abstraction with its two M1
implementations (SABnzbd and the built-in GetComics DDL client), the tracked-download
state machine that turns client state into queue visibility, and the failure loop
(failed → blocklist → automatic re-search) that makes acquisition self-healing.

## What Changes

Implements 25 approved baseline requirements (no new IDs; scenario elaboration only):

- **Client abstraction (FRG-DL-001, 002)** — one interface (download → id, get-items,
  remove, mark-imported, status/test) with SABnzbd + built-in DDL as implementations;
  provider-row config with schema/test endpoints (same seam as indexers); protocol-
  matched dispatch; client failure at grab time = release stays pending, never lost.
- **SABnzbd (FRG-DL-003..005)** — server-side NZB fetch (through the indexer's
  back-off ladder + egress policy) with validation, then `mode=addfile` upload;
  queue/history polling mapped to typed states (incl. encrypted/failed detection);
  remote path mapping for completed items.
- **Tracking (FRG-DL-006..008)** — grab history keyed by client download ID (the join
  key for everything downstream); the tracked-download state machine on a ~1-min
  command loop matching client items to grab history (re-parse fallback via the
  change-2 parser); `GET /api/v1/queue` built exclusively from tracked state
  (FRG-API-007) — nothing polls clients at request time.
- **Failure loop (FRG-DL-011..013)** — failed handling; multi-field blocklist
  (backing change 4's BlocklistSpecification, now live); automatic re-search command
  on failure. Grab handoff from change 4 goes live: approved releases actually
  download.
- **DDL client (FRG-DDL-001..013)** — GetComics search provider feeding the shared
  decision engine (escalating query ladder, pagination cap, roundup skipping);
  versioned fixture-backed page adapter that fails gracefully on layout drift; link
  enumeration by quality-tier/host with configurable priority and paywall rejection;
  per-host failover into the standard failed pipeline; politeness reusing the
  change-4 back-off ladder (≥15s page fetches); persistent serialized restart-
  surviving download queue (on the SCHED backbone, download pool = 1); streaming
  download with size accounting; Range-validated safe resume; content verification
  before import handoff (magic bytes + archive sanity); system-generated safe
  filenames with the `[__issueid__]` handshake tag; outbound URL security via the
  `external` egress profile per hop; import handoff with provenance (indexer/DDL
  source recorded for blocklist).

**Deliberately deferred to change 6:** FRG-DL-009 (completed-download handling) and
FRG-DL-010 (post-import cleanup) — they require the shared import pipeline. In this
change, completed downloads park at state "awaiting import" and are visible in the
queue as such.

## Capabilities

### New Capabilities

None — all requirements exist in the approved baseline specs.

### Modified Capabilities

- `dl`: FRG-DL-001..008, 011, 012, 013
- `ddl`: FRG-DDL-001..013
- `api`: FRG-API-007

## Non-goals

- No import execution (change 6 owns PP + DL-009/010).
- No SABnzbd retry passthrough (FRG-DL-014, B), no pack/booktype recognition
  (FRG-DDL-014, B), no archive extraction (FRG-DDL-015, B — DDL downloads land as
  single files in M1), no Cloudflare/FlareSolverr (FRG-DDL-016, B), no mirror hosts
  (FRG-DDL-017, B), no torrents (parked to B per the 2026-07-05 milestone reshape).
- No UI (change 7); queue is API-only here.

## Impact

- **New code**: `backend/src/foragerr/{downloads/, ddl/}`, queue API router, Alembic
  migration for download_clients, grab_history, tracked_downloads, blocklist,
  ddl_queue tables.
- **External services**: SABnzbd + GetComics via fixtures; SABnzbd contract tests
  against a recorded API surface; live verification manually at the change-7 gate.
- **Security**: DDL scrapes hostile HTML and follows scraped links — FRG-DDL-011/012
  are security-mandatory (safe filenames, egress re-validation per hop); risk rows
  RISK-007/008/009 (DDL SSRF/hostile content), RISK-029 (SAB path confusion)
  updated in this change (FRG-PROC-006). SABnzbd is a `local-service` egress profile
  consumer (operator-configured base URL).
- **Registry**: on merge, the 25 rows flip `approved → implemented`.

## Approval

- **Approver:** Adrian
- **Date:** 2026-07-04
- **Decision:** Approved under the standing grant of 2026-07-04 covering changes
  3-7. Implementation may begin, scoped to the 25 requirements listed above.
