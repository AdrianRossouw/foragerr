# nfr — delta for m2-hardening-performance

## MODIFIED Requirements

### Requirement: FRG-NFR-001 — startup time

The system SHALL be ready to serve (health endpoint 200, scheduler running) within 15 seconds of container start on the reference home server with a library of up to 5,000 issues, excluding one-time schema migrations.

- **Milestone**: M2
- **Source**: mylar-feature-surface.md §8 (Mylar's startup does table checks/migrations inline); sonarr-architecture.md §6 (startup re-queue work bounded).
- **Notes**: M1 measures and records the baseline; M2 enforces the budget. Startup must not block on any outbound network call (CV, indexers) — that sub-rule is the load-bearing part. **M2 elaboration (m2-hardening-performance)**: adds the timed budget acceptance, the no-outbound-at-startup guard, and — as a startup-robustness sub-property — an isolated-importability regression guard for the flows/importer seam (a module that cannot be imported cannot start; a re-opened import cycle surfaces as a startup `ImportError`). The seam residue is a fragility, not a live break: at proposal time every leaf module imports cleanly as the sole entry point; the guard pins that so it cannot regress. This scenario is homed here (rather than NFR-002/003 budgets or NFR-007 crash-safety) by that judgment; no new requirement id is allocated and module behavior stays byte-identical.

#### Scenario: Ready-to-serve within the startup budget

- **WHEN** the application starts against a seeded 5,000-issue database already at the head schema (migrations excluded), timed over N starts
- **THEN** each start reaches ready-to-serve — the root `/health` probe returns 200 **and** the scheduler is running — within 15 seconds at p95, in CI/soak runs

#### Scenario: Startup never blocks on an outbound network call

- **WHEN** the application starts with ComicVine and indexers configured but every outbound host unreachable (network blackholed)
- **THEN** startup still reaches ready-to-serve within the budget, and no startup hook issues or awaits an outbound HTTP request via the shared client factory (asserted by an at-startup outbound-call guard)

#### Scenario: Every module is importable as the sole entry point (import-cycle guard)

- **WHEN** each of the importer and library-flows leaf modules (`foragerr.importer`, `foragerr.importer.pipeline`, `foragerr.importer.sources`, `foragerr.library.flows`, `foragerr.library.flows.library_import`, `foragerr.library.flows.rename`, `foragerr.library.flows.rescan`, `foragerr.downloads`) is imported as the first and only import in a fresh interpreter
- **THEN** every import succeeds with no circular-import `ImportError`, so a re-introduced eager cycle across the flows/importer/downloads seam fails the guard rather than only a scoped test run

### Requirement: FRG-NFR-002 — library scan throughput

A full library rescan of 5,000 comic archive files on local storage SHALL complete within 10 minutes (parse + reconcile, excluding metadata network fetches), without blocking interactive API requests beyond the UI-responsiveness budget.

- **Milestone**: M2
- **Source**: mylar-feature-surface.md §4 (librarysync walks + parses everything); sonarr-architecture.md §5.5 (DiskScanService, shared import pipeline).
- **Notes**: Target sized to the owner's actual library scale ("a few thousand issues"). Scans run as SCHED commands in the PP/scan worker class so they cannot starve search/downloads. **M2 elaboration (m2-hardening-performance)**: the non-starvation structure already holds by construction — `library-import-scan` runs on the `pp` workload class, off-loads the filesystem walk/existence-sweep, replaces staging rows in one short write transaction before the (separate, capped) metadata proposal phase, and issues no per-file network fetch in the measured phase. This change adds the throughput benchmark and always-on structural guards over that shape.

#### Scenario: Seeded 5,000-file scan completes under the throughput budget

- **WHEN** a full rescan runs against a seeded library of 5,000 archive files across ~200 series on local storage (parse + reconcile + stage, excluding the metadata proposal fetches)
- **THEN** the scan completes under 10 minutes while a concurrent API smoke test stays within its NFR-003 latency budget (soak/perf run)

#### Scenario: Scan runs off the event loop on the pp class without starving reads

- **WHEN** the scan command's workload class and execution are inspected
- **THEN** the command carries `workload_class == "pp"`, its filesystem walk and existence sweep run through the off-load executor (never on the event loop) and hold no read-blocking exclusivity, and the measured parse/reconcile/stage phase issues no outbound HTTP request

### Requirement: FRG-NFR-003 — UI responsiveness at library scale

With a library of a few thousand issues (reference: 5,000), interactive read API endpoints backing UI pages (series list, series detail, queue, history, wanted) SHALL respond with p95 latency under 500 ms, using pagination on unbounded collections.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.2 (paging envelope for queue/history/blocklist/wanted); mylar-feature-surface.md (webserve.py 9.7k-line monolith as the anti-pattern).
- **Notes**: The paging envelope shape itself is API AREA; NFR owns the latency budget and the "never unbounded" rule. Aggregate stats (have/total counts) should be computed by query, not per-row Python loops (Sonarr's SeriesStats pattern). **M2 elaboration (m2-hardening-performance)**: the structural sub-rules are already implemented — the paging envelope carries a server-side page-size cap and `SeriesStatistics` is computed by SQL aggregate — so this change pins them with a cap audit and adds the latency benchmark.

#### Scenario: p95 latency under budget for the UI read endpoints

- **WHEN** a load test runs against the seeded 5,000-issue library over the series-list, series-detail, queue, history, and wanted read endpoints
- **THEN** each endpoint responds with p95 latency under 500 ms (perf run)

#### Scenario: Listed endpoints are always paged with a server-side cap and query-computed stats

- **WHEN** the series-list, queue, history, and wanted endpoints are requested with a page size above the server cap, and the series-detail/list stats are inspected
- **THEN** each returns a paged envelope (never an unbounded array) with the page size refused with a validation error when above the server-side cap (an oversize page is never served), and aggregate have/total stats come from a SQL aggregate query rather than a per-row Python loop

### Requirement: FRG-NFR-007 — crash-safe queues and idempotent work

A crash or power loss at any point SHALL NOT lose acknowledged work items or corrupt queue state: commands, download-queue items, and import handoffs SHALL be recoverable to a consistent state on restart, with at-least-once execution and idempotent handlers (no duplicate snatches or double imports).

- **Milestone**: M2
- **Source**: mylar-ddl.md §3.2 (state smeared across globals/DB/memory — restart loses order); sonarr-architecture.md §4.3-4.5 (download-id join key, state machine), §6.1 (persisted commands).
- **Notes**: SCHED owns the persistence mechanism; NFR owns the end-to-end crash property and the idempotency obligation on handlers (dedup keys: command payload hash, release guid, download id). M1 gets the mechanism; the fault-injection acceptance lands M2. **M2 elaboration (m2-hardening-performance)**: the mechanism and most handler idempotency are already implemented and tested (persisted command queue, download-id join, the already-registered import no-op, blocklist dedup carrying `pub_date`); this change adds the staged kill/restart fault-injection acceptance over them.

#### Scenario: Acknowledged commands survive restart

- **WHEN** a crash is simulated after a command is persisted in `queued`/`started` state and the application restarts
- **THEN** the command is recovered to a consistent state (still tracked / re-queued), with no acknowledged work item lost

#### Scenario: Re-snatching the same release is idempotent

- **WHEN** a snatch is re-executed for the same release guid / download id after a mid-download crash and restart
- **THEN** no duplicate grab or tracked-download row is created — the dedup key makes the handler at-least-once safe

#### Scenario: Re-importing an already-registered file is a no-op

- **WHEN** an import is re-run over a file whose path is already registered in the library after a pre-import-commit crash and restart
- **THEN** the file is treated as already imported and no duplicate `issue_files` row is created

### Requirement: FRG-NFR-014 — Listener request resource limits

The HTTP/WebSocket listener SHALL enforce configurable limits on inbound requests — maximum request body size, maximum header size, request timeout, and a basic per-client request rate/concurrency cap — rejecting over-limit requests with an appropriate 4xx (413/429) rather than consuming unbounded memory or wedging workers; SHALL enforce, for the WebSocket listener specifically, a configurable cap on concurrent connections (excess connections refused cleanly at the handshake without disturbing existing connections) and inbound-frame size and rate limits (an over-limit inbound frame closes that socket cleanly rather than buffering unbounded memory); and SHALL bound and sanitize any request value written into structured logs (no CR/LF log-forging).

- **Milestone**: M2
- **Source**: STRIDE analysis (no listener-level body/rate cap in the domain drafts; log-forging residual of FRG-NFR-012). Gap G-1; RISK-021, RISK-014.
- **Notes**: Reliability-shaped (availability + log integrity), hence NFR not SEC. Complements FRG-DEP structured logging and FRG-NFR secret redaction. **M2 implementation (m2-hardening-performance)**: HTTP limits land as a listener middleware on the HTTP scope only (so the request timeout and body cap never touch the long-lived WebSocket); the WS connection cap is a `WsBroadcaster.try_connect` refusal that leaves the registry and live sockets untouched, and the inbound size/rate limit is enforced inside the existing drain loop and returns through the existing teardown/close path so the M1 lifecycle correctness (register-before-accept; the client-gone close guard) is not regressed. All limits are configurable with documented, generous defaults and floors; the per-client rate cap is a single-user-tailnet DoS safety valve (0 disables it), not throttling or access control. This mitigates RISK-021 and closes the request-sourced arm of RISK-014.

#### Scenario: Oversize request body is rejected at the cap without buffering

- **WHEN** a request body exceeding the configured maximum body size is sent — including a body with an omitted or lying `Content-Length` that drips unboundedly
- **THEN** the request is rejected with 413 at the cap, no unbounded buffer is accumulated in memory, and the worker is released rather than wedged

#### Scenario: Oversize headers and slow requests are bounded

- **WHEN** a request presents headers exceeding the configured header-size cap, or a request that does not complete within the configured request timeout
- **THEN** the oversized-header request is rejected with a bounded 4xx and the timed-out request is aborted with a bounded response, in both cases releasing the worker rather than consuming unbounded resources — and the WebSocket connection is unaffected by the request timeout (enforced on the HTTP scope only)

#### Scenario: A burst of requests from one client is rate-limited

- **WHEN** a single client exceeds the configured per-client request rate/concurrency cap in a burst
- **THEN** the over-limit requests are rejected with 429 (carrying `Retry-After`), the limiter's own client table stays bounded, and setting the cap to 0 disables rate limiting entirely

#### Scenario: Excess WebSocket connections are refused cleanly

- **WHEN** the number of concurrent WebSocket connections reaches the configured cap and another client attempts to connect
- **THEN** the excess connection is refused cleanly at the handshake without registering, existing connections and the broadcast bus are undisturbed, and the register-before-accept ordering for accepted connections is preserved

#### Scenario: Oversize or flooding inbound WebSocket frames close that socket cleanly

- **WHEN** a connected WebSocket client sends an inbound frame larger than the configured inbound-frame cap, or floods inbound frames beyond the configured inbound rate
- **THEN** that socket is closed cleanly by the server without accumulating unbounded memory, through the endpoint's existing teardown path (no double close), while other clients and the bus continue unaffected

#### Scenario: Request fields with newline metacharacters are logged as one escaped field

- **WHEN** a request carries a value containing CR/LF or other control characters (e.g. in the path, query, or a header) that is written toward the structured logs
- **THEN** the logged form is bounded and sanitized so the value appears as a single escaped field, with no forged log lines — closing the request-sourced arm of the CR/LF log-forging residual
