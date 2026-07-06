## Why

This is the FINAL M2 change — the "own your library" milestone's hardening pass.
M2 changes 1–5.5 built and wired the daily loop and the operator surfaces
(add/search/download/import, mass ingestion, review screens, System
status/health/tasks, scheduled backups, first-run defaults, config hygiene).
What remains are the five **cross-cutting non-functional** rows that were
baselined in Phase 2 with only placeholder `Baseline acceptance` scenarios and
were deliberately parked to "the milestone change that implements each
requirement" (NFR spec Purpose). They are the promises a single admin relies on
to trust the tool unattended, and none of them has a tagged test yet:

1. **No listener resource limits (FRG-NFR-014, the load-bearing new work).**
   The HTTP/WebSocket listener enforces **no** inbound body-size cap, header cap,
   request timeout, or per-client rate/concurrency cap. This is the open
   mitigation for **RISK-021** (memory/CPU DoS from large or rapid requests,
   incl. WebSocket floods), which M1 shipped as a **documented latent** one
   milestone early: the WS per-socket *outbound* queues are bounded, but there
   is **no cap on concurrent WS connections and no inbound-frame limit**, so a
   tailnet-reachable client can still grow memory by opening many sockets or
   sending large inbound frames. It is also the residual arm of **RISK-014**
   (CR/LF log-forging) for *request-sourced* text. This change adds the limits
   and flips RISK-021 to mitigated.

2. **No startup-time budget test (FRG-NFR-001).** The 15 s ready-to-serve budget
   (health 200 + scheduler running, 5,000-issue library, excluding migrations)
   and its load-bearing sub-rule — *startup must not block on any outbound
   network call* — have no enforcing test. This change also folds in the
   **flows/importer import-cycle regression guard** here (a module that cannot be
   imported cannot start; see design for the judgment).

3. **No scan-throughput budget test (FRG-NFR-002).** The 10-minute full-rescan
   budget for 5,000 files (parse + reconcile, excluding metadata fetches) without
   starving interactive requests is unenforced.

4. **No UI-latency budget test (FRG-NFR-003).** The p95 < 500 ms budget for the
   read endpoints backing UI pages is unenforced. The structural sub-rules
   (paged envelopes with a server-side page-size cap; aggregate stats by query,
   not per-row loops) are **largely already implemented** (paging envelope +
   cap, `SeriesStatistics`); the gap is the latency benchmark and an audit that
   every listed endpoint is capped.

5. **No crash-safety fault-injection test (FRG-NFR-007).** The mechanism
   (persisted command queue, download-id join key, idempotent handlers) exists
   and much of the idempotency is already implemented and tested; the missing
   M2 piece is the explicit kill-and-restart acceptance tagged to NFR-007.

Grouping the five is deliberate: they are one hardening pass over the running
listener and its budgets, they share the security-docs update (RISK-021 flip),
and four of them are test-authoring against already-shipped mechanisms.

## What Changes

- **Listener request resource limits (FRG-NFR-014)** — the new attack-surface
  work:
  - **HTTP**: a listener middleware (`api/limits.py`) enforcing a maximum
    request body size (streamed + aborted at the cap with **413**, never
    buffered whole — including a lying/absent `Content-Length`), a maximum
    header size, a request timeout, and a basic **per-client rate/concurrency
    cap** (**429** on burst). All four are configurable with documented defaults
    and floors; the middleware runs on the HTTP scope only, so it never touches
    the long-lived WebSocket.
  - **WebSocket (RISK-021 core)**: a configurable **cap on concurrent WS
    connections** — the over-cap connection is refused cleanly at the handshake
    (the existing registry is untouched, existing sockets undisturbed) — and
    **inbound-frame size + rate limits** on the drain loop (the WS is
    server-push; inbound frames are only a disconnect detector, so an oversize
    or flooding inbound frame is a clean server-initiated close). The M1
    lifecycle correctness (register-before-accept; the client-gone teardown fix
    at `0e0456a`) is preserved — the inbound-limit path returns through the
    *existing* close path and does not add a second close.
  - **Log integrity (RISK-014 request arm)**: any request-sourced value written
    to structured logs is bounded and CR/LF-sanitized (reusing the FRG-NFR-012
    control-character stripper), so a newline-bearing path/header appears as one
    escaped field, never a forged log line.
- **Startup-time budget + import-cycle guard (FRG-NFR-001)**: a seeded
  5,000-issue startup benchmark asserting ready-within-budget (p95 over N
  starts, migrations excluded) and a **no-outbound-network-at-startup** guard;
  plus an **isolated-importability regression test** (every leaf module imports
  cleanly as the sole entry point in a fresh interpreter) and a small
  de-coupling of the `IMPORT_FILE_MUTATION_GROUP` seam so the guard cannot
  regress. Behavior is byte-identical (see design).
- **Scan-throughput budget (FRG-NFR-002)**: a seeded 5,000-file benchmark under
  the 10-minute budget with a concurrent API smoke staying within the NFR-003
  budget, plus always-on structural guards (scan runs on the `pp` worker class;
  the FS-heavy walk is off-loaded and does not hold a write transaction or issue
  a per-file network fetch across the measured phase).
- **UI-latency budget (FRG-NFR-003)**: a load-test benchmark asserting p95 <
  500 ms for the five listed read endpoints, plus an always-on audit that each
  returns a paged envelope with a server-enforced page-size cap and that
  aggregate stats are computed by SQL aggregate.
- **Crash-safe / idempotent work (FRG-NFR-007)**: staged kill-and-restart
  fault-injection (post-enqueue, mid-download, pre-import-commit) asserting no
  lost acknowledged item, no duplicate snatch (release-guid / download-id
  dedup), and no duplicate library rows (already-imported path), tagged to
  NFR-007.

## Capabilities

### New Capabilities

None. All five requirement IDs (FRG-NFR-001, -002, -003, -007, -014) are
pre-registered `approved` M2 rows; this change elaborates their placeholder
`Baseline acceptance` scenarios into real, testable behavior and lands the
implementation for the one that needs code (FRG-NFR-014).

### Modified Capabilities

- `nfr`:
  - FRG-NFR-001 (startup budget elaborated + no-outbound-at-startup guard +
    isolated-importability regression scenario — the flows/importer seam).
  - FRG-NFR-002 (scan-throughput budget elaborated + structural non-starvation
    guards).
  - FRG-NFR-003 (UI-latency budget elaborated; the paged-envelope/cap and
    by-query-stats sub-rules were already implemented and are now pinned).
  - FRG-NFR-007 (crash/restart fault-injection acceptance elaborated over the
    already-shipped persistence + idempotency mechanism).
  - FRG-NFR-014 (listener HTTP body/header/timeout/rate limits **and** the WS
    connection cap + inbound-frame limits — the RISK-021 mitigation — elaborated
    from placeholder and implemented).

## Impact

- **Code**: backend only.
  - New `foragerr/api/limits.py` listener middleware, installed in
    `register_api` (HTTP scope). `foragerr/ws/broadcast.py` gains a
    `max_connections` cap + a `try_connect()` that refuses over cap;
    `foragerr/ws/router.py` refuses the over-cap handshake and enforces the
    inbound size/rate limits inside `_drain_incoming` **through the existing
    teardown path**; `foragerr/ws/__init__.py` passes the configured limits.
  - New config keys (all documented, defaults + floors) in `foragerr/config.py`
    — flow automatically into the generated `config.yaml` via the existing
    `render_documented_config` treatment; interval-shaped keys join
    `INTERVAL_RANGES` for the clamp-with-warning path (FRG-NFR-009).
  - A small relocation/re-export of `IMPORT_FILE_MUTATION_GROUP` (byte-identical
    public API) to keep the import graph acyclic under the new regression test.
  - The rest is **test authoring**: startup/scan/latency benchmarks and the
    crash fault-injection suite over already-shipped mechanisms. No new API
    endpoints, no schema/migration, no frontend change.
- **DB**: none. No new tables, columns, or migrations.
- **Security docs (FRG-PROC-006)**: REQUIRED — this change hardens the listener
  (new middleware parsing untrusted request metadata; WS inbound handling).
  Declared as tasks: **flip RISK-021** in `docs/security/risk-register.md` from
  "Mitigate / documented latent" to **Mitigate (implemented)** with an
  m2-hardening status note (connection cap + inbound limits + HTTP body/rate
  caps landed); add an m2-hardening note to **RISK-014** recording that the
  CR/LF log-forging residual is now closed for *request-sourced* fields (the DDL
  scraped-text arm is unchanged, still tracked); and a `threat-model.md` delta
  updating the G-1 listener note (§interfaces) and the COMP 2 WebSocket
  documented-latent to their mitigated state. No new outbound surface, no
  secrets exposed.
- **Manual (FRG-PROC-011)**: small, admin-facing. Declared section (carried out
  as a task): `docs/manual/admin/configuration.md` — the new listener/WS limit
  settings (max body size, header size, request timeout, per-client rate cap;
  WS max connections + inbound-frame size/rate), their defaults and floors, and
  the note that the rate cap is a safety valve for the single-user tailnet
  (0 disables it). The NFR *budgets* (startup/scan/latency/crash) are internal
  quality gates with no user- or admin-facing behavior change, so no other
  manual section is touched (plus the one-line docs/manual/index.md currency-statement update every change carries).
- **Dependencies / SOUP (FRG-PROC-012)**: none anticipated — the middleware uses
  Starlette (already present via FastAPI) + stdlib + the existing sanitizer;
  benchmarks use the existing test stack. `tools/soup_check.py` is expected to
  exit 0 unchanged. If implementation elects a new dependency,
  `docs/security/soup-register.md` is updated in this same change.

## Non-goals

- **No authentication / Origin validation.** The WS connection cap and inbound
  limits are availability controls, not access control; CSWSH Origin validation
  (RISK-022) and app auth (RISK-020) stay deferred to M5 as recorded. The rate
  cap is keyed by peer address as a DoS safety valve, not an auth mechanism.
- **No resource-footprint budget (FRG-NFR-013).** The 512 MB RSS soak budget is
  milestone B (measured from M2 soak runs, enforced later) and is **out of
  scope** — not in this change's id set.
- **No new API endpoints, no metrics/telemetry surface.** The limits are
  listener-level; over-limit requests get a plain 413/429, not a new resource.
- **No frontend change.** All five rows are backend/quality; the UI already
  consumes paged envelopes.
- **No DDL scraped-text sanitizer.** RISK-014's DDL text arm is a separate,
  already-tracked residual; this change closes only the *request-sourced* CR/LF
  arm at the listener.
- **No change to the outbound HTTP limits (FRG-NFR-006)** or the per-provider
  politeness/backoff (FRG-NFR-005) — those are implemented M1 and untouched;
  this change is about the **inbound** listener.

## Approval

Adrian pre-approved this change on 2026-07-06 under the M2/M3 standing
FRG-PROC-009 grant. His words, verbatim:

> keep going with m2/m3 and all their related changes as you go. I'll come check in later

Recorded per the standing-grant model already used for the preceding M2
changes; m2-hardening-performance (M2 change 6, the final M2 change) falls
squarely within that grant's scope.
