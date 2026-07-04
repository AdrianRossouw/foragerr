# Tasks

## 1. Backend scaffold (shared foundation for all work areas)

- [x] 1.1 Create `backend/pyproject.toml` (uv, Python 3.12, src layout) with FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, aiosqlite, httpx, pytest, pytest-asyncio; register the `req` pytest marker (FRG-API-001, FRG-PROC-004)
- [x] 1.2 App factory `foragerr.app:create_app` with lifespan hooks, `/api/v1` router mount, uvicorn entrypoint on port 8789 (FRG-API-001)
- [x] 1.3 Config: pydantic-settings models, `/config` dir resolution, `config.yaml` first-run generation with commented defaults, `FORAGERR_*` env precedence, secret fields registry, fail-fast validation with interval clamping (FRG-DEP-002, FRG-DEP-003, FRG-DEP-005, FRG-NFR-009)
- [x] 1.4 Structured logging: key-value formatter, stdout + size-rotated `/config/logs/foragerr.log`, configurable level, redaction filter masking registered secrets and api_key-shaped params in messages/args/tracebacks (FRG-DEP-006, FRG-NFR-008)

## 2. Persistence (worktree area: db)

- [ ] 2.1 Async engine + session factories with per-connection PRAGMAs (WAL, busy_timeout, foreign_keys, synchronous=NORMAL) (FRG-DB-001, FRG-DB-005)
- [ ] 2.2 `write_session()` single-writer context manager with bounded busy retry + post-commit event hook (FRG-DB-006, FRG-DB-007)
- [ ] 2.3 Alembic setup, programmatic startup upgrade, revision guard refusing newer-schema DBs with clear error (FRG-DB-002, FRG-DB-004)
- [ ] 2.4 Pre-migration WAL-checkpointed backup to `/config/backups/pre-migration-<version>-<ts>/` with retention pruning (FRG-DB-003)
- [ ] 2.5 Base model conventions: typed columns, TEXT issue numbers, sentinel rejection validators (FRG-DB-008)
- [ ] 2.6 Tagged tests: PRAGMA assertions, migration up/no-op/failure/newer-schema cases, backup+retention, concurrent-writer stress (zero locked errors), transaction rollback, sentinel round-trips (FRG-DB-001..008)

## 3. Command backbone (worktree area: sched)

- [ ] 3.1 Pydantic command models (discriminated union), `commands` table, enqueue API with payload validation and (name, payload-hash) dedup among queued/started (FRG-SCHED-001, FRG-SCHED-003)
- [ ] 3.2 Worker pools per workload class (search=1, download=1, pp=1, default=2), priority claim order, exclusivity-group locks, `asyncio.to_thread` offload helper (FRG-SCHED-004, FRG-SCHED-005)
- [ ] 3.3 Startup orphan recovery re-queuing `started` rows; queued rows survive unclean restart (FRG-SCHED-002)
- [ ] 3.4 Interval scheduler: `scheduled_tasks` table, ≤60s tick loop, min-interval clamping, persisted last_run, force-run resetting the timer (FRG-SCHED-006, FRG-SCHED-007)
- [ ] 3.5 `job_history` rows per execution (trigger, timings, outcome, verbatim error) + housekeeping retention pruning (FRG-SCHED-008)
- [ ] 3.6 Event bus: typed subscribe/publish, per-handler isolation, post-commit publication wired to `write_session()` (FRG-SCHED-009)
- [ ] 3.7 Graceful drain on shutdown: stop claims, bounded grace, persist final states; wire into lifespan SIGTERM path (FRG-SCHED-011, FRG-DEP-008)
- [ ] 3.8 Tagged tests: lifecycle, failure capture, dedup, priority, exclusivity, pool caps, starvation isolation, orphan recovery, scheduler due/not-due/clamp/restart, history, bus isolation, post-commit events, drain (FRG-SCHED-001..009, FRG-SCHED-011)

## 4. Outbound HTTP factory (worktree area: http)

- [ ] 4.1 Client factory: mandatory timeouts, TLS verify always on, streaming byte cap, manual redirect walk (max 5) (FRG-NFR-006)
- [ ] 4.2 Egress validation: scheme check, DNS resolution refusing loopback/link-local/private/ULA, per-hop re-validation, `external` vs `local-service` profiles, no cross-integration credential forwarding (FRG-SEC-001)
- [ ] 4.3 Hostile-fixture test corpus: IP-literal loopback, decimal/hex IP encodings, redirect-to-private, oversize body, slow-drip, hung server, 6-hop redirect chain (FRG-NFR-006, FRG-SEC-001)
- [ ] 4.4 Static guard test: no `httpx`/`requests` call sites outside the factory; no `print(` in `backend/src/` (FRG-NFR-006, FRG-NFR-008)

## 5. API skeleton, health, version (worktree area: api)

- [ ] 5.1 Uniform 4xx error shape `{"message", "errors[]"}` with Pydantic validation mapping; no default `{"detail"}` leak (FRG-API-002)
- [ ] 5.2 Paging-envelope helper with whitelisted sort keys mapped to fixed column expressions; unknown key → 400 (FRG-API-002)
- [ ] 5.3 `GET /health` (unauthenticated; DB/scheduler/migration component statuses; non-2xx when unhealthy) and version/build info endpoint + startup log line with dev fallbacks (FRG-DEP-007, FRG-DEP-010)
- [ ] 5.4 `POST /api/v1/command` + `GET /api/v1/command/{id}` transport over the backbone with a no-op test command; OpenAPI accuracy test at `/api/v1/openapi.json` (FRG-API-001, FRG-SCHED-007)
- [ ] 5.5 AUTH-001 tests: route inventory asserts no auth middleware/dependency; all surfaces respond credential-free; no dormant auth code (FRG-AUTH-001)
- [ ] 5.6 No-self-update guard test: no update code path, version fixed at build (FRG-DEP-009)

## 6. Security docs, traceability, merge gate

- [ ] 6.1 Update `docs/security/risk-register.md`: RISK-020 restated with compensating control; RISK-025 DNS-rebinding TOCTOU accepted-residual note; RISK-012/013/036 mitigation status → implemented-by FRG-NFR-006/008 + FRG-SEC-001; matching STRIDE threat-model deltas (FRG-PROC-006, FRG-AUTH-001, FRG-SEC-001)
- [ ] 6.2 Verify every in-scope FRG ID has ≥1 passing tagged test; flip the 33 registry rows to `implemented`; regenerate matrix via `tools/trace.py` (exit 0) (FRG-PROC-004, FRG-PROC-005)
- [ ] 6.3 Full suite green; demo run via uvicorn with temp config dir (health, command round-trip, graceful shutdown); `--no-ff` merge to main; archive change; delete branch (FRG-PROC-007)
