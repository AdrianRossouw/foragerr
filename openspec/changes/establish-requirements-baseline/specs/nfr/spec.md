# nfr Spec Delta

## ADDED Requirements


### Requirement: FRG-NFR-001 — startup time

The system SHALL be ready to serve (health endpoint 200, scheduler running) within 15 seconds of container start on the reference home server with a library of up to 5,000 issues, excluding one-time schema migrations.

- **Milestone**: M2
- **Source**: mylar-feature-surface.md §8 (Mylar's startup does table checks/migrations inline); sonarr-architecture.md §6 (startup re-queue work bounded).
- **Notes**: M1 measures and records the baseline; M2 enforces the budget. Startup must not block on any outbound network call (CV, indexers) — that sub-rule is the load-bearing part.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Timed container starts against a seeded 5,000-issue database pass the threshold in CI/soak runs (p95 over 5 starts).

### Requirement: FRG-NFR-002 — library scan throughput

A full library rescan of 5,000 comic archive files on local storage SHALL complete within 10 minutes (parse + reconcile, excluding metadata network fetches), without blocking interactive API requests beyond the UI-responsiveness budget.

- **Milestone**: M2
- **Source**: mylar-feature-surface.md §4 (librarysync walks + parses everything); sonarr-architecture.md §5.5 (DiskScanService, shared import pipeline).
- **Notes**: Target sized to the owner's actual library scale ("a few thousand issues"). Scans run as SCHED commands in the PP/scan worker class so they cannot starve search/downloads.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Seeded-library benchmark (5,000 files across ~200 series) completes a scan under the threshold while a concurrent API smoke test stays within its latency budget.

### Requirement: FRG-NFR-003 — UI responsiveness at library scale

With a library of a few thousand issues (reference: 5,000), interactive read API endpoints backing UI pages (series list, series detail, queue, history, wanted) SHALL respond with p95 latency under 500 ms, using pagination on unbounded collections.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.2 (paging envelope for queue/history/blocklist/wanted); mylar-feature-surface.md (webserve.py 9.7k-line monolith as the anti-pattern).
- **Notes**: The paging envelope shape itself is API AREA; NFR owns the latency budget and the "never unbounded" rule. Aggregate stats (have/total counts) should be computed by query, not per-row Python loops (Sonarr's SeriesStats pattern).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Load test against the seeded library shows p95 < 500 ms for the listed endpoints; queue/history/wanted endpoints return paged envelopes, never unbounded arrays.

### Requirement: FRG-NFR-004 — ComicVine rate limiting

The system SHALL enforce a client-side ComicVine rate limit shared across ALL concurrent operations (default: max 1 request per 2 s, configurable with a floor), and on rate-limit/ban signals SHALL back off, mark the ComicVine backend degraded, and NOT retry in a tight loop.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.3 and §3.1 (fixed sleep, unlocked concurrency, no Retry-After handling — weaknesses to fix), §5 (candidate requirement).
- **Notes**: Divergence from Mylar: a real shared limiter (async token/lock), not a per-call sleep. CV client behavior (endpoints, pagination) is META's; NFR owns the politeness budget.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A test driving concurrent refresh+search operations records inter-request spacing ≥ the limit at the HTTP layer; a simulated ban response flips CV health to degraded and suppresses further calls for the cool-down.

### Requirement: FRG-NFR-005 — indexer and DDL politeness with failure backoff

The system SHALL enforce per-provider minimum request intervals with jitter (defaults: search serialization with inter-search delay; DDL page fetches ≥ 15 s apart; bounded pagination depth), and on provider failures SHALL escalate through a persisted backoff ladder (temporary disable with automatic recovery), honoring Retry-After where present.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §2.6 (EscalationBackOff ladder — "copy verbatim"); mylar-ddl.md §1.8 and §3.7 (DDL_QUERY_DELAY, self-disable, no-jitter/no-429-handling gaps); mylar-feature-surface.md §3 (SEARCH_DELAY, provider blocks).
- **Notes**: One shared politeness/backoff mechanism consumed by IDX/SRCH/DDL — those AREAs own which requests happen; NFR owns pacing and failure escalation. Persist backoff state so restarts don't reset a ban-avoidance cool-down.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Provider request logs show spacing/jitter per policy; consecutive simulated failures walk the documented backoff ladder (e.g., 1 m → 5 m → 15 m → ... → 24 h max) and a success de-escalates; a disabled provider is skipped by search/RSS and shown degraded.

### Requirement: FRG-NFR-006 — bounded, verified outbound requests

Every outbound HTTP request SHALL have explicit connect and read timeouts, TLS certificate verification enabled by default (any per-host override is explicit, logged, and security-documented), a bounded redirect count, and bounded response size where the response is parsed.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §4 (no timeout in cv.pulldetails; CV_VERIFY global disable); mylar-ddl.md §4 (verify=False to FlareSolverr, blind redirect following, SSRF).
- **Notes**: Enforce by funnelling all outbound traffic through one shared client factory — makes the acceptance testable and gives NFR redaction and politeness a single choke point.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Static/code-review check (or HTTP-client wrapper test) shows no timeout-less or verify=False call sites; a hung mock server fails the request at the timeout instead of wedging a worker.

### Requirement: FRG-NFR-007 — crash-safe queues and idempotent work

A crash or power loss at any point SHALL NOT lose acknowledged work items or corrupt queue state: commands, download-queue items, and import handoffs SHALL be recoverable to a consistent state on restart, with at-least-once execution and idempotent handlers (no duplicate snatches or double imports).

- **Milestone**: M2
- **Source**: mylar-ddl.md §3.2 (state smeared across globals/DB/memory — restart loses order); sonarr-architecture.md §4.3-4.5 (download-id join key, state machine), §6.1 (persisted commands).
- **Notes**: SCHED owns the persistence mechanism; NFR owns the end-to-end crash property and the idempotency obligation on handlers (dedup keys: command payload hash, release guid, download id). M1 gets the mechanism; the fault-injection acceptance lands M2.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Kill -9 fault-injection at staged points (post-enqueue, mid-download, pre-import- commit) followed by restart yields: item still tracked, no duplicate download of the same release, no duplicate library rows.

### Requirement: FRG-NFR-008 — secret redaction in logs and errors

The system SHALL redact secret material (API keys, passwords, session tokens, auth headers, key-bearing URLs) from all log output, error messages, exception traces, and diagnostic artifacts.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.2/§4 (CV key embedded in logged URLs); mylar-feature-surface.md §8 (carepackage stripping); CLAUDE.md Secrets ("never echo them into files, logs").
- **Notes**: Implement as a logging filter plus the outbound-client choke point — the same machinery serves the DEP diagnostic bundle. Complements (does not replace) "send keys outside the URL".

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A test configuring known sentinel secret values exercises logging-heavy paths (CV calls, indexer errors, login failures) and asserts the sentinels never appear in captured logs; the shared HTTP client logs URLs with credential query params masked.

### Requirement: FRG-NFR-009 — configuration validation at startup

The system SHALL validate the entire effective configuration (types, ranges, interval minimums, required-when-enabled dependencies, path existence/writability) at startup, failing fast with messages naming each offending key and expected form; out-of-range intervals are clamped with a warning rather than failing.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §7 (typed _CONFIG_DEFINITIONS, interval min-clamping); sonarr-architecture.md §7.2 (validated settings contracts).
- **Notes**: Pydantic settings models give this nearly for free. DEP owns config sources/precedence /migration; NFR owns validation semantics — dedup hint for the orchestrator.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A config with a bad type, an impossible path, and a too-small interval produces: startup failure listing the first two by key name, and (with those fixed) a clamped interval plus warning for the third.

### Requirement: FRG-NFR-010 — resilience to external-service failure

Failure or unavailability of any external service (ComicVine, indexers, SABnzbd, GetComics, mirror hosts) SHALL NOT crash the application or wedge worker pools; affected operations SHALL fail with recorded, user-visible status while unrelated features continue.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.3/§1.8 (BACKENDSTATUS flags, log-and-continue); sonarr-architecture.md §3.5 (DownloadClientUnavailable pending reason), §2.4 (per-indexer errors swallowed in RSS fan-out).
- **Notes**: Per-handler isolation (SCHED event bus) + per-provider backoff (above) + bounded requests (above) together imply this; baselined separately because it is the testable end-to-end property.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With ComicVine mocked down, library browsing, OPDS, and SAB tracking still work and refresh jobs record failure status; with SAB down, grabs park as pending (per SRCH/DL behavior) and the UI shows the client unreachable.

### Requirement: FRG-NFR-011 — observable component health

The system SHALL track and expose per-component health (ComicVine, each indexer, SAB, DDL provider, scheduler, database) with last-success/last-failure timestamps and current state (ok / degraded / disabled-until), via API for UI display.

- **Milestone**: M2
- **Source**: mylar-comicvine.md §1.3 (BACKENDSTATUS_CV surfaced in UI); sonarr-architecture.md §2.6/§7.1 (indexer status, Health resource).
- **Notes**: Aggregates into DEP's health endpoint (container-level) but is the richer per-provider view. M1 exposes raw states; M2 completes the UI surface.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Forcing an indexer into backoff shows it degraded with its disabled-until time in the health API/UI; recovery clears it without restart.

### Requirement: FRG-NFR-012 — untrusted external content handling

All strings originating from external services (ComicVine wiki fields, scraped DDL pages, release titles, filenames from redirects) SHALL be treated as untrusted: HTML-stripped or sanitized on ingest, encoded on output, never interpolated into shell commands, SQL, log format strings, or filesystem paths without sanitization; filenames for downloaded content SHALL be generated by the system, not taken from remote URLs.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §4 (user-editable wiki HTML → UI/search); mylar-ddl.md §4 (redirect-derived filenames, hostile archives, scraped text into logs/DB/UI).
- **Notes**: Cross-cutting security NFR feeding docs/security/ STRIDE (FRG-PROC-006). Archive-bomb /extraction limits belong to the DDL/PP AREAs; this requirement owns the string-handling discipline everywhere.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Tests feed hostile fixtures (script tags in CV descriptions, path-traversal filenames in redirect URLs, format-string metacharacters in titles) through ingest paths and assert sanitized persistence, encoded rendering, and system-generated download filenames.

### Requirement: FRG-NFR-013 — resource footprint

The system SHALL operate within a steady-state memory budget of 512 MB RSS on the reference home server with the reference 5,000-issue library, with no unbounded in-memory caches or queues (all long collections bounded or persisted).

- **Milestone**: B
- **Source**: mylar-feature-surface.md (56k-line monolith with global in-memory queues as the cautionary reference); sonarr-architecture.md §6.2 (bounded workers).
- **Notes**: Deliberately backlog: measured from M2 soak runs, enforced later. The bounded- collections sub-rule is designed-in from M1 even though the budget test comes later.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A 24-hour soak (scheduled jobs cycling, several downloads) stays under the RSS budget with no monotonic growth trend.


### Requirement: FRG-NFR-014 — Listener request resource limits

The HTTP/WebSocket listener SHALL enforce configurable limits on inbound requests — maximum request body size, maximum header size, request timeout, and a basic per-client request rate/concurrency cap — rejecting over-limit requests with an appropriate 4xx (413/429) rather than consuming unbounded memory or wedging workers, and SHALL bound and sanitize any request value written into structured logs (no CR/LF log-forging).

- **Milestone**: M2
- **Source**: STRIDE analysis (no listener-level body/rate cap in the domain drafts; log-forging residual of FRG-NFR-012). Gap G-1; RISK-021, RISK-014.
- **Notes**: Reliability-shaped (availability + log integrity), hence NFR not SEC. Complements FRG-DEP structured logging and FRG-NFR secret redaction.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A multi-gigabyte body upload is rejected at the limit without memory exhaustion; a burst of requests is rate-limited with 429s; a request field containing newline metacharacters appears in logs as a single escaped field, not forged log lines.
