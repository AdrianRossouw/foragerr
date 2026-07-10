# NFR — Cross-Cutting Non-Functional Requirements Specification

## Purpose

Baseline requirements for cross-cutting non-functional requirements, mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).
## Requirements
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

### Requirement: FRG-NFR-004 — ComicVine rate limiting

The system SHALL enforce a client-side ComicVine rate limit shared across ALL concurrent operations (default: max 1 request per 2 s, configurable with a floor), and on rate-limit/ban signals SHALL back off, mark the ComicVine backend degraded, and NOT retry in a tight loop.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.3 and §3.1 (fixed sleep, unlocked concurrency, no Retry-After handling — weaknesses to fix), §5 (candidate requirement).
- **Notes**: Divergence from Mylar: a real shared limiter (async token/lock), not a per-call sleep. CV client behavior (endpoints, pagination) is META's; NFR owns the politeness budget.

#### Scenario: Limiter is process-global across all call sites

- **WHEN** concurrent ComicVine operations spanning search, volume, issue, and cover call sites are driven simultaneously
- **THEN** observed inter-request wire times at the HTTP layer are serialized to at least the configured minimum interval across all call sites combined, never per-call-site independent spacing

#### Scenario: 429 with Retry-After is honored

- **WHEN** ComicVine returns a 429 response carrying a `Retry-After` header
- **THEN** the limiter suppresses further ComicVine requests until at least the Retry-After delay has elapsed and does not retry in a tight loop

#### Scenario: Ban/degraded state is observable via health

- **WHEN** a simulated ComicVine ban/rate-limit signal is received
- **THEN** the ComicVine backend is marked degraded in the exposed component health, and further calls are suppressed for the cool-down window rather than reissued immediately

#### Scenario: Configured interval below the floor is clamped

- **WHEN** the limiter interval is configured below the documented floor
- **THEN** the effective interval is clamped to the floor (with a warning) and enforced spacing never drops below that documented minimum

### Requirement: FRG-NFR-005 — indexer and DDL politeness with failure backoff

The system SHALL enforce per-provider minimum request intervals with jitter (defaults: search serialization with inter-search delay; DDL page fetches ≥ 15 s apart; bounded pagination depth), and on provider failures SHALL escalate through a persisted backoff ladder (temporary disable with automatic recovery), honoring Retry-After where present.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §2.6 (EscalationBackOff ladder — "copy verbatim"); mylar-ddl.md §1.8 and §3.7 (DDL_QUERY_DELAY, self-disable, no-jitter/no-429-handling gaps); mylar-feature-surface.md §3 (SEARCH_DELAY, provider blocks).
- **Notes**: One shared politeness/backoff mechanism consumed by IDX/SRCH/DDL — those AREAs own which requests happen; NFR owns pacing and failure escalation. Persist backoff state so restarts don't reset a ban-avoidance cool-down.

#### Scenario: Per-indexer 2 s spacing gate is enforced

- **WHEN** multiple requests to the same indexer are issued back-to-back from any fetch path
- **THEN** consecutive requests to that provider are spaced at least 2 s apart at the HTTP layer, and the spacing gate is applied per-indexer (a busy provider does not delay requests to a different one)

#### Scenario: Consecutive failures walk the persisted escalating back-off ladder

- **WHEN** a provider returns consecutive failures
- **THEN** its disable-until state escalates through the documented ladder (1 m → ... → 24 h maximum), the ladder state is persisted so a restart does not reset the cool-down, and a single subsequent success resets the provider to no back-off

#### Scenario: Retry-After and auth failures fast-forward the ladder

- **WHEN** a provider returns a Retry-After header, or an authentication failure
- **THEN** the back-off is fast-forwarded to at least the honored interval rather than starting at the bottom of the ladder

#### Scenario: A backing-off provider is skipped by fetch paths and logged

- **WHEN** a search or RSS fetch path selects providers while one provider is within its disable-until window
- **THEN** that provider is skipped (no request is issued) and the skip is logged, while the backlog search's inter-search delay never drops below its documented floor

### Requirement: FRG-NFR-006 — bounded, verified outbound requests

Every outbound HTTP request SHALL have explicit connect and read timeouts, TLS certificate verification enabled by default (any per-host override is explicit, logged, and security-documented), a bounded redirect count, and bounded response size where the response is parsed.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §4 (no timeout in cv.pulldetails; CV_VERIFY global disable); mylar-ddl.md §4 (verify=False to FlareSolverr, blind redirect following, SSRF).
- **Notes**: Enforce by funnelling all outbound traffic through one shared client factory — makes the acceptance testable and gives NFR redaction and politeness a single choke point.

#### Scenario: All outbound traffic flows through the shared client factory with timeouts and TLS verify

- **WHEN** the codebase is checked for outbound HTTP call sites (static check plus client-construction test)
- **THEN** every outbound request is issued via the single shared `httpx.AsyncClient` factory with no direct `httpx`/`requests` call site outside it, every client the factory produces carries explicit connect, read, write, and pool timeouts (none defaulted to unlimited), and TLS certificate verification is enabled with no per-call or per-host opt-out parameter exposed by the factory API

#### Scenario: Hung server aborts at the configured timeout

- **WHEN** a request is made through the factory client to a mock server that accepts the connection but never sends a response body
- **THEN** the request fails with a timeout error at the configured read timeout (observed duration within tolerance of the configured value), and the calling worker/task is released rather than wedged

#### Scenario: Redirect chain is walked manually and bounded at 5 hops

- **WHEN** a mock server returns a chain of 6 redirect responses
- **THEN** the client (auto-redirects disabled; hops walked manually) stops after the 5th hop and raises a bounded too-many-redirects error, and a 4-hop chain to a valid target succeeds with each hop observable to the egress-validation layer (FRG-SEC-001)

#### Scenario: Oversize and slow-drip responses are aborted by the streaming byte cap

- **WHEN** a parsed-response fetch streams a body that exceeds the configured maximum byte cap (including a server that omits/lies in Content-Length and drips an unbounded body)
- **THEN** the response is aborted at the cap with a bounded, logged error; no unbounded buffer is accumulated in memory and the partial body is not handed to any parser

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

### Requirement: FRG-NFR-008 — secret redaction in logs and errors

The system SHALL redact secret material (API keys, passwords, session tokens, auth headers, key-bearing URLs) from all log output, error messages, exception traces, and diagnostic artifacts.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.2/§4 (CV key embedded in logged URLs); mylar-feature-surface.md §8 (carepackage stripping); CLAUDE.md Secrets ("never echo them into files, logs").
- **Notes**: Implement as a logging filter plus the outbound-client choke point — the same machinery serves the DEP diagnostic bundle. Complements (does not replace) "send keys outside the URL".

#### Scenario: Registered secret values never reach any handler unmasked

- **WHEN** the configuration is loaded with known sentinel secret values (API keys, passwords) and logging-heavy paths are exercised (outbound client errors, config dumps, failure paths)
- **THEN** each secret-valued config field self-registers with the redaction filter at config load time, and the sentinel values never appear in output captured from any attached log handler — every occurrence is replaced with a mask token

#### Scenario: Redaction covers messages, args, and formatted exception traces

- **WHEN** log records are emitted that carry a sentinel secret (a) inline in the message string, (b) via a `%s`/args parameter, and (c) inside the text of a formatted exception traceback (e.g., an httpx error whose URL embeds the key)
- **THEN** all three record forms are masked before reaching any handler; the captured output for each case contains the mask token and not the sentinel

#### Scenario: api_key-shaped URL query parameters are masked

- **WHEN** a URL containing a credential-bearing query parameter (e.g., `?api_key=…`, `?apikey=…`) is logged by the shared HTTP client or any other path
- **THEN** the parameter value appears masked in the captured log line even if that specific value was not pre-registered as a config secret, while non-secret query parameters remain readable

### Requirement: FRG-NFR-009 — configuration validation at startup

The system SHALL validate the entire effective configuration (types, ranges, interval minimums, required-when-enabled dependencies, path existence/writability) at startup, failing fast with messages naming each offending key and expected form; out-of-range intervals are clamped with a warning rather than failing.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §7 (typed _CONFIG_DEFINITIONS, interval min-clamping); sonarr-architecture.md §7.2 (validated settings contracts).
- **Notes**: Pydantic settings models give this nearly for free. DEP owns config sources/precedence /migration; NFR owns validation semantics — dedup hint for the orchestrator.

#### Scenario: Invalid configuration fails fast with field-precise errors

- **WHEN** the application starts with a configuration containing a wrong-typed value and a nonexistent/unwritable required path
- **THEN** startup fails before the listener binds, with a pydantic-settings validation report naming each offending key (field-precise, both errors reported in one pass) and the expected form/type for each

#### Scenario: Startup failure exits non-zero

- **WHEN** the process is launched with an invalid configuration
- **THEN** the process terminates with a non-zero exit code (observable to the container supervisor) rather than continuing in a partially configured state

#### Scenario: Out-of-range intervals are clamped with a warning

- **WHEN** the configuration supplies a polling/politeness interval below its documented safe floor (where the spec designates clamping rather than rejection)
- **THEN** startup succeeds, the effective value is the documented floor, and a warning log names the key, the supplied value, and the clamped value

### Requirement: FRG-NFR-010 — resilience to external-service failure

Failure or unavailability of any external service (ComicVine, indexers, SABnzbd, GetComics, mirror hosts) SHALL NOT crash the application or wedge worker pools; affected operations SHALL fail with recorded, user-visible status while unrelated features continue.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.3/§1.8 (BACKENDSTATUS flags, log-and-continue); sonarr-architecture.md §3.5 (DownloadClientUnavailable pending reason), §2.4 (per-indexer errors swallowed in RSS fan-out).
- **Notes**: Per-handler isolation (SCHED event bus) + per-provider backoff (above) + bounded requests (above) together imply this; baselined separately because it is the testable end-to-end property.

#### Scenario: A hostile/slow indexer cannot wedge the search worker pool

- **WHEN** a search command runs against a fixture indexer that misbehaves — accepts the connection then hangs, drips bytes slowly, returns junk, or 429-storms
- **THEN** the request to that indexer is bounded by connect/read timeouts and a response byte cap, the misbehaving provider is isolated by the back-off ladder, and no search worker is left wedged

#### Scenario: Other indexers in the same command still complete

- **WHEN** the same multi-indexer search command includes both the misbehaving fixture provider and one or more healthy providers
- **THEN** the healthy providers are searched and return their results, the misbehaving provider's failure is recorded as user-visible status, and the search worker completes rather than crashing the pool

#### Scenario: End-to-end misbehaving-fixture-server test

- **WHEN** an end-to-end test drives a real search against a fixture server exhibiting the hostile/slow behaviors
- **THEN** the application does not crash or exhaust the worker pool, the failure is recorded against the provider, and unrelated features continue to operate

### Requirement: FRG-NFR-011 — observable component health

The system SHALL track and expose per-component health (ComicVine, each indexer, SAB/download clients, DDL provider, scheduler, database, root folders, disk space) with last-success/last-failure timestamps and current state (ok / degraded / disabled-until), via `GET /api/v1/system/health` for the UI. A single health-aggregation service SHALL compute the component list from already-persisted or cheap-live state (the per-provider back-off table, filesystem free-space and writability, database integrity and last-backup age, scheduler status) and derive BOTH this per-component view and the FRG-API-014 `/api/v1/health` warnings list from it — the checks owned by other areas are read, not re-implemented. A component that recovers SHALL clear on the next poll without a restart.

- **Milestone**: M2
- **Source**: mylar-comicvine.md §1.3 (BACKENDSTATUS_CV surfaced in UI); sonarr-architecture.md §2.6/§7.1 (indexer status, Health resource).
- **Notes**: Aggregates into DEP's root `/health` liveness (container-level up/down) but is the richer per-provider view. Reuses `providers/backoff.py::ProviderBackoff.health()` (level / disabled-until / last-failure — FRG-NFR-005/IDX-010) for the provider components, root-folder free-space (already surfaced on Media Management), and the FRG-DB-012 integrity result + FRG-DB-009 last-backup age for the `database` component — no new tracking table. Surfacing is poll-first (React Query refetch): low-frequency, and recovery clears on the next poll. A disk-space component warns below a documented low-space floor.

#### Scenario: An indexer in back-off shows degraded with its disabled-until time

- **WHEN** an indexer is forced into failure back-off and `GET /api/v1/system/health` is requested
- **THEN** that indexer component reports `degraded`/`disabled-until` with its disabled-until timestamp and last-failure time, and after the back-off recovers a subsequent poll shows it `ok` again with no restart

#### Scenario: Every tracked component is represented with state and timestamps

- **WHEN** `GET /api/v1/system/health` is requested
- **THEN** ComicVine, each configured indexer, each download client, the DDL provider, the scheduler, the database, each root folder, and disk space each appear with a state (ok / degraded / disabled-until) and last-success/last-failure timestamps where applicable

#### Scenario: The warnings list and the per-component view derive from one service

- **WHEN** the same underlying state produces both `GET /api/v1/health` and `GET /api/v1/system/health`
- **THEN** the two never disagree — the warnings list is exactly the non-ok subset of the per-component view (each warning carrying a remediation hint), computed by the single aggregation service rather than a parallel check path

#### Scenario: Database health reflects integrity and last backup

- **WHEN** the database component is inspected after a failed integrity check or with a stale/absent last scheduled backup
- **THEN** the `database` component reports the corresponding error/warning (integrity failure named; a missing or overdue backup surfaced) and returns to `ok` once integrity passes and a recent backup exists

### Requirement: FRG-NFR-012 — untrusted external content handling

All strings originating from external services (ComicVine wiki fields, scraped DDL pages, release titles, filenames from redirects) SHALL be treated as untrusted: HTML-stripped or sanitized on ingest, encoded on output, never interpolated into shell commands, SQL, log format strings, or filesystem paths without sanitization; filenames for downloaded content SHALL be generated by the system, not taken from remote URLs.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §4 (user-editable wiki HTML → UI/search); mylar-ddl.md §4 (redirect-derived filenames, hostile archives, scraped text into logs/DB/UI).
- **Notes**: Cross-cutting security NFR feeding docs/security/ STRIDE (FRG-PROC-006). Archive-bomb /extraction limits belong to the DDL/PP AREAs; this requirement owns the string-handling discipline everywhere.

#### Scenario: HTML is stripped and length-capped at ingest

- **WHEN** a ComicVine description containing `<script>` and other HTML tags exceeding the length cap is ingested
- **THEN** the value persisted to the database has HTML removed and is truncated to the documented length cap, and that same sanitized text is what appears in API responses and logs

#### Scenario: Path traversal in a title cannot escape the target directory

- **WHEN** a series or issue title contains path-traversal and separator sequences (e.g. `../`, embedded `/` or `\`, a reserved device name)
- **THEN** filesystem path segments are built only from sanitized safe components with separators and reserved names stripped, so the resulting path stays within the intended library directory

#### Scenario: Control/ANSI characters do not reach logs unescaped

- **WHEN** an externally sourced string containing ANSI escape and control characters (including CR/LF) is written toward the logs
- **THEN** the logged form is sanitized so no raw control sequences or forged log lines appear

#### Scenario: Hostile fixture round-trips harmlessly end to end

- **WHEN** a hostile fixture combining script tags, path traversal in the title, and ANSI/control characters is fed through the ingest paths
- **THEN** it persists sanitized, renders/serializes encoded, produces a system-generated (not remote-derived) download filename, and causes no injection, traversal, or log-forging side effects

### Requirement: FRG-NFR-013 — resource footprint

The system SHALL operate within a steady-state memory budget of 512 MB RSS on the reference home server with the reference 5,000-issue library, with no unbounded in-memory caches or queues (all long collections bounded or persisted).

- **Milestone**: B
- **Source**: mylar-feature-surface.md (56k-line monolith with global in-memory queues as the cautionary reference); sonarr-architecture.md §6.2 (bounded workers).
- **Notes**: Deliberately backlog: measured from M2 soak runs, enforced later. The bounded- collections sub-rule is designed-in from M1 even though the budget test comes later.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A 24-hour soak (scheduled jobs cycling, several downloads) stays under the RSS budget with no monotonic growth trend.

### Requirement: FRG-NFR-014 — Listener request resource limits

The HTTP/WebSocket listener SHALL enforce configurable limits on inbound requests — maximum request body size, maximum header size, request timeout, and a basic per-client request rate/concurrency cap — rejecting over-limit requests with an appropriate bounded status (e.g. 413/429/431, or 503 for a timed-out request) rather than consuming unbounded memory or wedging workers; SHALL enforce, for the WebSocket listener specifically, a configurable cap on concurrent connections (excess connections refused cleanly at the handshake without disturbing existing connections) and inbound-frame size and rate limits (an over-limit inbound frame closes that socket cleanly rather than buffering unbounded memory); and SHALL bound and sanitize any request value written into structured logs (no CR/LF log-forging).

- **Milestone**: M2
- **Source**: STRIDE analysis (no listener-level body/rate cap in the domain drafts; log-forging residual of FRG-NFR-012). Gap G-1; RISK-021, RISK-014.
- **Notes**: Reliability-shaped (availability + log integrity), hence NFR not SEC. Complements FRG-DEP structured logging and FRG-NFR secret redaction. **M2 implementation (m2-hardening-performance)**: HTTP limits land as a listener middleware on the HTTP scope only (so the request timeout and body cap never touch the long-lived WebSocket); the WS connection cap is a `WsBroadcaster.try_connect` refusal that leaves the registry and live sockets untouched, and the inbound size/rate limit is enforced inside the existing drain loop and returns through the existing teardown/close path so the M1 lifecycle correctness (register-before-accept; the client-gone close guard) is not regressed. All limits are configurable with documented, generous defaults and floors; the per-client rate cap is a single-user-tailnet DoS safety valve (0 disables it), not throttling or access control. This mitigates RISK-021 and closes the request-sourced arm of RISK-014.

#### Scenario: Oversize request body is rejected at the cap without buffering

- **WHEN** a request body exceeding the configured maximum body size is sent — including a body with an omitted or lying `Content-Length` that drips unboundedly
- **THEN** the request is rejected with 413 at the cap, no unbounded buffer is accumulated in memory, and the worker is released rather than wedged

#### Scenario: Oversize headers and slow requests are bounded

- **WHEN** a request presents headers exceeding the configured header-size cap, or a request whose handler produces no first response byte within the configured request timeout
- **THEN** the oversized-header request is rejected with a bounded 4xx and the first-byte-timed-out request is aborted with a bounded response, in both cases releasing the worker rather than consuming unbounded resources — the timeout bounds time-to-first-response-byte only, so an already-streaming response (e.g. an OPDS file download) is never truncated by it, and the WebSocket connection is unaffected (enforced on the HTTP scope only)

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


### Requirement: FRG-NFR-015 — Bounded log capture with configurable retention

The in-app log buffer (FRG-API-021) SHALL be bounded by construction: its
capacity in records comes from configuration
(`log_buffer_records` / `FORAGERR_LOG_BUFFER_RECORDS`, default 2000),
validated at startup (a non-positive or non-integer value fails fast per
FRG-NFR-009), and the buffer SHALL never hold more than that many records —
the oldest record is evicted on overflow. Capture SHALL be O(1) per record
with no I/O in the logging hot path, and each buffered record SHALL store
only the already-formatted message so buffer memory is proportional to the
record cap.

- **Milestone**: M4 (m4-logs-viewer)
- **Source**: owner request 2026-07-10 (retention configuration).
- **Notes**: Retention here is capacity, not duration — a deliberate
  simplification for a memory-only buffer. **Audit-trail position**: this is
  an operator observability surface, not an audit log. A durable
  access/audit-log requirement (attribution, tamper evidence, retention
  policy) is deferred to the auth milestone — before authentication there
  are no distinct principals to attribute actions to. Recorded so the
  regulated-development trail shows the deferral was deliberate.

#### Scenario: Buffer never exceeds its configured bound

- **WHEN** more records than `log_buffer_records` are emitted
- **THEN** the buffer holds exactly the configured number of newest records and the oldest have been evicted

#### Scenario: Invalid retention setting fails fast

- **WHEN** the process starts with `FORAGERR_LOG_BUFFER_RECORDS=0` or a non-numeric value
- **THEN** startup fails with an actionable configuration error naming the setting
