# Change: m1-foundation — platform backbone for the M1 vertical slice

## Why

Phase 3 (approved plan, 2026-07-04) implements M1 as seven changes; this is change 1 of 7.
Every subsequent change hangs off shared platform machinery — persistence, the command
queue, configuration, logging, the outbound HTTP choke point, and the API skeleton — so
that machinery must land first, fully tested, rather than accrete ad hoc inside feature
changes.

## What Changes

Implements 33 approved baseline requirements (no new IDs; scenario elaboration only):

- **Persistence (FRG-DB-001..008)** — single SQLite DB under `/config`; WAL +
  busy_timeout + foreign-keys PRAGMAs on every connection; Alembic forward-only
  migrations applied at startup; pre-migration backup with retention; refuse-to-start on
  newer schema; single-writer discipline; transactional multi-step ops; typed
  sentinel-free schema conventions (decimal/suffix-safe issue numbers as TEXT).
- **Background-work backbone (FRG-SCHED-001..009, 011)** — typed command model;
  persisted command queue surviving restart with orphan re-queue; de-duplication by
  type+payload; priority + exclusivity groups; bounded asyncio worker pools partitioned
  by workload class; interval scheduler loop (≤60s tick, no APScheduler); force-run;
  persisted job history; in-process event bus with per-handler isolation, publish after
  commit; graceful drain on shutdown.
- **Runtime & ops (FRG-DEP-002,003,005..010)** — all persistent state under `/config`;
  env-over-file config; no secrets in image/repo; structured logging (stdout + rotating
  file); unauthenticated `/health`; graceful SIGTERM shutdown incl. WAL checkpoint; no
  self-update; version/build info. (Docker image itself, FRG-DEP-001/011, lands in
  change 7.)
- **Cross-cutting safety (FRG-NFR-006,008,009 · FRG-SEC-001)** — single shared async
  HTTP-client factory funnelling all outbound traffic: mandatory timeouts, TLS verify
  on, bounded redirects and response sizes, SSRF egress controls (refuse
  loopback/link-local/RFC-1918, re-validate every redirect hop); secret redaction filter
  in logs/errors; fail-fast Pydantic config validation at startup.
- **No-auth risk acceptance (FRG-AUTH-001)** — auth mode "none" on all surfaces,
  documented against RISK-020; no half-built auth code paths.
- **API skeleton (FRG-API-001,002)** — FastAPI app factory; `/api/v1` prefix; generated
  OpenAPI; standard REST/error conventions and the paging-envelope utility
  (`{page,pageSize,sortKey,sortDirection,totalRecords,records[]}`) with whitelisted sort
  keys.

## Capabilities

### New Capabilities

None — all requirements exist in the approved baseline specs.

### Modified Capabilities

Delta specs elaborate M1 acceptance scenarios (baseline carried one coarse scenario per
requirement; FRG-PROC-003/009 defer elaboration to milestone changes):

- `db`: FRG-DB-001..008 scenario elaboration
- `sched`: FRG-SCHED-001..009, 011 scenario elaboration
- `dep`: FRG-DEP-002,003,005..010 scenario elaboration
- `nfr`: FRG-NFR-006,008,009 scenario elaboration
- `sec`: FRG-SEC-001 scenario elaboration (hostile-fixture acceptance)
- `auth`: FRG-AUTH-001 scenario elaboration
- `api`: FRG-API-001,002 scenario elaboration

## Non-goals

- No product domain code: no series/issue entities, no ComicVine, no indexers, no
  downloads, no UI (changes 3–7).
- No Docker image build (FRG-DEP-001) or Tailscale exposure docs (FRG-DEP-011) — those
  ship with the runnable slice in change 7; this change keeps the app runnable via
  `uvicorn` locally.
- No WebSocket push (FRG-API-010, change 7) and no command-status push (FRG-SCHED-010,
  M2) — M1 command tracking polls `GET /api/v1/command/{id}`.
- No authentication implementation of any kind (M3).
- No scheduled DB backups/restore/integrity checks (FRG-DB-009/010/012, M2) — only the
  event-triggered pre-migration backup.

## Impact

- **New code**: `backend/` created — `backend/src/foragerr/` (app factory, config,
  logging, db, migrations, commands/scheduler/events, http client factory, health,
  version) and `backend/tests/` (layout is load-bearing: `tools/trace.py` greps
  `backend/tests/**/*.py` for FRG IDs).
- **Dependencies**: Python 3.12, uv-managed; FastAPI, Pydantic v2, SQLAlchemy 2.x,
  Alembic, aiosqlite, httpx, pytest, pytest-asyncio.
- **Security**: new attack surface = HTTP listener (health/API skeleton) + outbound HTTP
  factory. `docs/security/` risk register rows referenced and updated in this change:
  RISK-020 (no-auth acceptance restated), RISK-025/RISK-012/RISK-036 (SSRF/TLS/timeout
  controls at the factory), RISK-013 (redaction). STRIDE threat-model deltas recorded in
  the same change (FRG-PROC-006).
- **Registry**: on merge, the 33 rows flip `approved → implemented`.

## Approval

- **Approver:** Adrian
- **Date:** 2026-07-04
- **Decision:** Approved (paired change-1/change-2 gate per the approved Phase 3
  plan). Implementation may begin, scoped to the 33 requirements listed above.
