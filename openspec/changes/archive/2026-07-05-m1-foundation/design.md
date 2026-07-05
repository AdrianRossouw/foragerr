# Design: m1-foundation

## Context

Greenfield `backend/` tree. Everything later in Phase 3 (ComicVine client, indexers,
downloads, import pipeline, API/UI/OPDS) consumes the machinery built here. The specs
already fix the hard constraints: SQLite WAL under `/config`, alembic-style forward-only
migrations, persisted/de-duplicated command queue on asyncio worker pools, hand-rolled
≤60s scheduler tick (explicitly not APScheduler), one shared outbound HTTP choke point,
env-over-file config, port 8789, no auth in M1 (RISK-020, Tailscale compensating
control).

## Goals / Non-Goals

**Goals:** a runnable, tested FastAPI app skeleton (`uvicorn foragerr.app:create_app`)
with persistence, migrations, command backbone, config, logging, health/version, and the
hardened HTTP factory — every FRG ID in scope carrying at least one tagged passing test.

**Non-Goals:** any domain entity or feature behavior (changes 3–7); Docker packaging
(change 7); WebSocket push (change 7 / M2); backups beyond pre-migration (M2); auth (M3).

## Decisions

1. **Package layout** — `backend/pyproject.toml` (uv-managed, Python 3.12), src layout:
   `backend/src/foragerr/{app.py, config.py, logging.py, db/, commands/, events/,
   http/, api/}` with tests in `backend/tests/` (path is load-bearing for
   `tools/trace.py` tag discovery). One package now; no premature service split.

2. **DB access: SQLAlchemy 2.x async (aiosqlite) + Alembic, single-writer via an
   application-level async write lock.** Every connection gets
   `journal_mode=WAL, busy_timeout, foreign_keys=ON, synchronous=NORMAL` via an engine
   connect hook. All mutating work goes through a `write_session()` context manager that
   serializes writers (FRG-DB-006) and commits transactionally (FRG-DB-007); readers use
   plain sessions. Alternative considered: a dedicated writer task with a queue —
   rejected as more moving parts for the same guarantee at M1 scale.

3. **Migrations at startup, guarded** (FRG-DB-002/003/004): startup sequence = open DB →
   read Alembic revision → if DB newer than code, refuse to start with a clear error →
   if upgrade pending, copy the DB file (plus `-wal`/`-shm` checkpointed) to
   `/config/backups/pre-migration-<version>-<ts>/` with retention pruning → run
   `alembic upgrade head` programmatically. Forward-only: no downgrade scripts ever.

4. **Command backbone** (FRG-SCHED-001..005): commands are Pydantic models in a
   discriminated union (`name` + payload) persisted to a `commands` table
   (status queued/started/completed/failed/cancelled, priority, exclusivity group,
   payload JSON, timestamps, result/error). Enqueue de-duplicates on (name,
   payload-hash) among queued/started rows (FRG-SCHED-003). Worker pools are asyncio
   tasks partitioned by workload class — M1 classes `search=1`, `download=1`, `pp=1`,
   `default=2` — pulling highest-priority eligible rows; exclusivity groups enforced by
   in-process asyncio locks keyed by group (FRG-SCHED-004). Startup re-queues orphaned
   `started` rows (FRG-SCHED-002). Blocking work inside handlers uses
   `asyncio.to_thread`.

5. **Scheduler + history + events** (FRG-SCHED-006..009): a `scheduled_tasks` table
   (name, interval, last_run) driven by one loop task with ≤60s tick that enqueues due
   commands; force-run = enqueue now + reset timer (FRG-SCHED-007). Every command
   execution writes a `job_history` row (FRG-SCHED-008). Event bus is an in-process
   registry `subscribe(EventType) / publish(event)` where each handler runs isolated
   (own task + try/except; one failing handler never blocks others, FRG-SCHED-009).
   Events for DB-backed operations are published only after commit (hook on the
   `write_session()` exit) per FRG-DB-007/FRG-SCHED-009.

6. **Graceful shutdown** (FRG-SCHED-011 + FRG-DEP-008): SIGTERM → stop accepting new
   commands, let in-flight handlers finish within a bounded grace (< 30s, configurable),
   persist still-queued rows untouched, WAL-checkpoint, exit 0. Uvicorn lifespan hooks
   own the ordering.

7. **Config** (FRG-DEP-002/003/005 + FRG-NFR-009): pydantic-settings models; sources =
   `/config/config.yaml` (created with commented defaults on first run) overridden by
   `FORAGERR_*` env vars; secrets only via env/config, never defaults, never logged.
   Invalid values fail startup with field-precise errors; numeric intervals clamp to
   documented safe ranges with a warning where the spec allows.

8. **Logging + redaction** (FRG-DEP-006 + FRG-NFR-008): stdlib `logging` with a
   structured key-value formatter (no extra dependency), stdout handler + size-rotated
   `/config/logs/foragerr.log`. A redaction `logging.Filter` masks values of registered
   secret config fields and `api_key`-shaped query params anywhere in messages/args;
   exception formatting passes through the same filter. Secrets register themselves at
   config-load time so later changes inherit redaction for free.

9. **Outbound HTTP factory** (FRG-NFR-006 + FRG-SEC-001): one module builds every
   outbound `httpx.AsyncClient`. Defaults: connect/read/write/pool timeouts, TLS verify
   on (no per-call opt-out parameter exposed), bounded response size (streaming reads
   with a byte cap), `follow_redirects=False` — redirects are walked manually (max 5),
   and **every hop** re-validates: scheme ∈ {http, https}, DNS-resolve the host and
   reject if any resolved address is loopback/link-local/private/ULA (unless the
   specific integration is explicitly configured as LAN-allowed — SABnzbd on the home
   LAN is legitimate, so egress policy is per-client-profile: `external` (default,
   private ranges refused) vs `local-service` (operator-configured base URL allowed)).
   Residual DNS-rebinding TOCTOU between check and connect is recorded in the risk
   register as accepted at home-server threat level. Hostile-fixture tests cover
   loopback/private/redirect-to-private/oversize-body/slow-response cases.

10. **API skeleton** (FRG-API-001/002 + FRG-DEP-007/010): FastAPI app factory, routers
    under `/api/v1`, OpenAPI served at `/api/v1/openapi.json`; uniform error shape
    `{"message", "errors[]"}` for 4xx incl. Pydantic validation mapping; paging-envelope
    helper with per-endpoint whitelisted sort keys (shared defense cited by RISK-002);
    unauthenticated `GET /health` (liveness + component placeholders) and version/build
    info endpoint; `POST /api/v1/command` + `GET /api/v1/command/{id}` ride the command
    backbone (FRG-API-005 formally lands in change 3, but the transport is exercised
    here via a no-op test command).

11. **AUTH-001** is verified by tests asserting no auth middleware/dependency exists and
    that `/health` and `/api/v1/*` respond without credentials, plus the risk-register
    cross-reference (RISK-020) restated in this change's security delta.

## Risks / Trade-offs

- [Single asyncio write lock serializes all writers] → acceptable at M1 scale (single
  user); stress test asserts zero unhandled `database is locked` under concurrent
  writers (FRG-DB-006 acceptance).
- [SSRF DNS re-resolution TOCTOU] → documented accepted residual (RISK-025 note);
  per-hop validation + no-redirect-following-by-default is the M1 bar.
- [Redaction is filter-based, not taint-based] → secrets that bypass `logging` (e.g.
  print) aren't covered; mitigated by convention tests grepping for `print(` in
  `backend/src/`.
- [Alembic at startup can fail mid-upgrade] → pre-migration backup + forward-only
  revisions + refuse-newer-schema make recovery manual-restore simple; documented in
  ops notes.
- [Hand-rolled scheduler/queue vs library] → deliberate spec divergence from Mylar's
  APScheduler; small surface, fully owned and testable.

## Migration Plan

Greenfield — no data migration. Rollback = don't merge the branch. The app must run
locally via `uv run uvicorn` with a temp `/config` for the change-gate demo.

## Open Questions

None blocking — config file format fixed as YAML; workload-class pool sizes are config
values with the defaults above.
