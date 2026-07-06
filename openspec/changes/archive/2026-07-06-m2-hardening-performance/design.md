# Design — m2-hardening-performance

Cross-cutting hardening for the final M2 change. One section per requirement,
each stating the gap (already-satisfied vs new work), the mechanism, and the
chosen defaults. Everything here is grounded in the code at `5ab3ed0`.

## Per-NFR gap analysis (summary)

| Req | Mechanism status | New work in this change |
|-----|------------------|-------------------------|
| FRG-NFR-014 | **Not implemented** (no listener limits; WS latent) | HTTP body/header/timeout/rate middleware + WS connection cap + inbound-frame limits + request-field log sanitization. **The code deliverable.** |
| FRG-NFR-001 | Startup exists; **no budget test**, no import guard | Timed 5k startup budget + no-outbound-at-startup guard + isolated-importability regression + seam de-couple |
| FRG-NFR-002 | Scan exists on `pp` pool, off-loaded walk; **no budget test** | Throughput benchmark + structural non-starvation guards |
| FRG-NFR-003 | **Sub-rules already implemented** (paged envelope + server cap; `SeriesStatistics` by query) | Latency benchmark + cap audit over the 5 endpoints |
| FRG-NFR-007 | Mechanism + most idempotency **already implemented/tested** | Staged kill/restart fault-injection acceptance |

The honest shape of this change: **FRG-NFR-014 is real code**; the other four are
predominantly **test authoring** that turns shipped-but-unverified behavior into
tagged, enforcing acceptance — with FRG-NFR-001 also carrying the small
import-seam de-couple.

---

## FRG-NFR-014 — listener request resource limits (the code work)

### 1. HTTP request limits — `foragerr/api/limits.py`

A single listener middleware installed in `register_api` (so it wraps every
`/api/v1`, `/opds`, `/health`, and SPA route). It runs on the **HTTP ASGI scope
only** — a `BaseHTTPMiddleware`/pure-ASGI middleware never sees the `websocket`
scope — so the request timeout and body cap **cannot** touch the long-lived WS
(that surface is handled in §2). Four controls:

- **Body size cap** (`listener_max_body_bytes`, default **8 MiB**, floor 64 KiB).
  foragerr has **no inbound file-upload endpoint** (SABnzbd add is *outbound*;
  OPDS is *download*; every API body is small JSON), so 8 MiB is generous
  headroom, not a functional limit. Enforcement is **streaming**: if
  `Content-Length` exceeds the cap → immediate **413** before reading; for a
  chunked/absent/lying `Content-Length`, the middleware wraps `receive` and
  counts bytes, aborting at the cap with 413 so no unbounded buffer accrues
  (the acceptance drives a multi-GiB drip with an omitted `Content-Length`).
- **Header size cap** (`listener_max_header_bytes`, default **16 KiB**). Total
  header-bytes over cap → **431**/**400**. (uvicorn/h11 already impose a coarse
  cap; owning it here makes the budget explicit and testable.)
- **Request timeout** (`listener_request_timeout_seconds`, default **30 s**,
  clamped range). The handler is run under `asyncio.wait_for`; on expiry the
  worker/task is released and a bounded **503** (Service Unavailable /
  timeout) is returned rather than wedging. Endpoints return quickly (heavy work
  is queued as SCHED commands), so 30 s is comfortable headroom. **WS is
  excluded by scope**, and any deliberately-streaming HTTP response (none today)
  would be exempted explicitly.
- **Per-client rate / concurrency cap** (`listener_rate_max_requests` per
  `listener_rate_window_seconds`, defaults **240 / 1 s**; **0 disables**).
  Keyed by peer address, an in-memory sliding-window counter with a **bounded**
  client table (LRU-capped so the limiter itself cannot grow unboundedly —
  single-user tailnet means one or two real peers). Over budget → **429** with a
  `Retry-After`. This is a DoS safety valve, **not** throttling or auth; the
  generous default and the `0` off-switch keep it out of the way of the normal
  single admin, and it is documented as such.

### 2. WebSocket connection cap + inbound limits (RISK-021 core)

The WS is server-push (`WsBroadcaster` → per-socket bounded outbound queue). The
inbound channel exists **only** as a disconnect detector (`_drain_incoming`
`receive_text()`-loops and discards). Two limits, designed to **not regress** the
M1 lifecycle correctness (register-before-accept; the client-gone teardown fix at
`0e0456a`).

**Connection cap** (`ws_max_connections`, default **32**, floor 1). The
broadcaster already tracks `connection_count`. Add `max_connections` to
`WsBroadcaster` and a `try_connect()` that returns `None` when
`connection_count >= max_connections` (single event-loop thread — no lock needed,
consistent with `broadcast.py`'s stated threading model) and otherwise registers
and returns the `Connection` exactly as `connect()` does today. The router:

```
conn = broadcaster.try_connect()
if conn is None:
    await websocket.close(code=1013)   # pre-accept close → clean handshake refusal
    return
# ... unchanged from here: accept, pump, _drain_incoming, existing teardown ...
```

The refusal happens **before** `accept()` and **without** registering, so the
existing registry and every live socket are untouched — the load-bearing
register-before-accept ordering for *accepted* sockets is preserved verbatim.

**Inbound size + rate limits** (`ws_max_inbound_bytes`, default **4 KiB**;
`ws_max_inbound_messages_per_second`, default **10**). `_drain_incoming` switches
from `receive_text()` to inspecting each frame's length and arrival cadence:
- an inbound text/binary frame larger than `ws_max_inbound_bytes`, or a burst
  exceeding the per-second rate, is anomalous (the server ignores inbound
  content) → log once and **return**;
- crucially it returns with the **client-still-connected** disposition
  (`False`, the existing "not a client disconnect" return value), so the
  endpoint's `finally` performs its **normal** close through the *existing*
  `if not client_gone: await websocket.close()` path. **No second close is
  added**, and the `client_gone` computation (the `0e0456a` fix) is unchanged:
  a genuine `WebSocketDisconnect` still returns `True` and still suppresses our
  close. Optionally the server-initiated close carries code `1009`
  (message-too-big); the correctness requirement is only that we do not
  double-close.

This keeps the whole delta to: one field + one method on `WsBroadcaster`, a
three-line pre-accept guard in the router, and a size/rate check inside the
existing drain loop.

### 3. Request-field log sanitization (RISK-014 request arm)

Any request-sourced string the listener writes to structured logs (method, path,
query, a header echoed in a warning) is passed through the existing
FRG-NFR-012 control-character stripper before it reaches a handler, so CR/LF and
ANSI sequences cannot forge a log line. Where foragerr emits no request field
today the property holds by construction and is pinned by a guard test; the
middleware's own over-limit warnings (413/429) sanitize the offending
request value they name.

### Config keys (documented-config treatment)

All keys land in `Settings` with `Field(description=...)`, so
`render_documented_config` emits them into `config.yaml` automatically (FRG-DEP-003)
and the admin manual documents them. The two interval-shaped keys
(`listener_request_timeout_seconds`, `listener_rate_window_seconds`) join
`INTERVAL_RANGES` for clamp-with-warning (FRG-NFR-009). Defaults chosen to be
**generous** so nothing in the single-admin happy path is ever refused; the
limits bite only under the abusive shapes RISK-021 describes.

---

## FRG-NFR-001 — startup budget + the flows/importer import-cycle guard

### Startup budget

Timed container/app starts against a seeded 5,000-issue database assert
**ready-to-serve** (root `/health` 200 **and** `app.state.scheduler` running)
within 15 s, p95 over N starts, **excluding** one-time schema migrations
(measured with the schema already at head). Plus the load-bearing sub-rule: a
startup with ComicVine/indexers *configured but unreachable* still reaches ready
within budget — asserted by a **no-outbound-HTTP-during-startup** guard (the
startup hooks touch only the DB/scheduler/first-run marker; none awaits the
shared HTTP factory). This is the honest enforcement of "startup must not block
on any outbound network call."

### The import-cycle residue (verified current state)

Empirically at `5ab3ed0`, **every** relevant module imports cleanly as the sole
entry point in a fresh interpreter — `foragerr.importer`,
`importer.pipeline`, `importer.sources`, `library.flows`,
`library.flows.library_import`, `library.flows.rename`, `library.flows.rescan`,
`foragerr.downloads` all succeed. So there is **no live `ImportError`**. The
residue tracked since ch3 is now **structural fragility**, not a break:

1. The importer package's clean importability rests on a **hand-maintained
   deferred import**: `importer/sources.py` defers its `foragerr.downloads`
   import into `CompletedDownloadSource.gather` precisely because the eager path
   `downloads → clients → search_ops → library.flows → library_import →
   foragerr.importer` closes a cycle. The guard is a **code comment**, with no
   test — re-introducing a top-level `foragerr.downloads` import in `sources.py`
   (or the importer `__init__`) would silently re-open the cycle.
2. The shared exclusivity-group **seam** `IMPORT_FILE_MUTATION_GROUP` lives in
   the heavyweight `foragerr.importer.__init__`, so every flows module that only
   needs the constant + `ImportContext` (`rename.py`, `rescan.py`) transitively
   imports the whole pipeline + ORM registration to get a string.

### Fix (behavior byte-identical)

- **Regression guard (load-bearing):** a pytest that imports each leaf module as
  the **sole entry point in a fresh subprocess** (so no other module has
  primed `sys.modules`) and asserts success — pinning isolated-importability so
  any re-introduced cycle fails CI instead of a scoped test run.
- **De-couple the seam (modest):** define `IMPORT_FILE_MUTATION_GROUP` in a tiny
  neutral leaf (`foragerr/importer/context.py`, which is already a
  dependency-free-ish leaf, or a new `foragerr/importer/_seam.py`) and
  **re-export it unchanged** from `foragerr.importer.__init__` (public API
  byte-identical). Flows modules that only need the constant import the leaf; the
  full-pipeline importers keep importing the package. The deferred
  `foragerr.downloads` import in `sources.py` stays (it is the correct fix for
  the *other* leg); the new test guards it.

**Why FRG-NFR-001 owns this.** Of the five cluster ids, startup-time is the
natural home: a module that cannot be imported cannot start, and a re-opened
cycle manifests as a startup `ImportError`. It is not crash-safety (NFR-007) nor
a latency/throughput budget (NFR-002/003). The isolated-importability scenario is
added to FRG-NFR-001 with a note recording this judgment. No new requirement id
is allocated — this is a robustness sub-property of an existing row, keeping
behavior byte-identical.

---

## FRG-NFR-002 — scan-throughput budget

**Already-satisfied structure:** `scan_library_root` runs as the
`library-import-scan` command on the `pp` workload class, off-loads the FS-heavy
walk/existence-sweep via `offload`, replaces staging rows in **one short write
transaction** *before* the (network) proposal phase, and performs **no per-file
ComicVine fetch** in the parse/reconcile/stage path (proposals are capped and
separate). So the budget's "does not starve interactive requests" and "excluding
metadata network fetches" boundaries already hold by construction.

**New work:**
- A seeded **5,000-file** benchmark (≈200 series) that the parse + reconcile +
  stage phase completes under **10 minutes**, run as an opt-in perf/soak test
  (marked like the other baseline-acceptance soaks) while a concurrent API smoke
  stays within the NFR-003 latency budget.
- Always-on **structural guards** (cheap, CI-default): the scan command carries
  `workload_class == "pp"` and takes no read-blocking exclusivity; the walk runs
  through `offload` (not on the event loop); the measured phase issues no
  outbound HTTP. These pin the non-starvation design so a refactor cannot move
  the heavy walk onto the loop or add a per-file fetch unnoticed.

---

## FRG-NFR-003 — UI-latency budget

**Already-satisfied sub-rules (pin, don't build):** the paging envelope with a
**server-side page-size cap** exists (`api/paging.py`, `test_api_paging.py`,
RISK-002 note) and `SeriesStatistics` is computed by SQL aggregate
(`library/repo.py`), matching the "aggregate stats by query, not per-row Python"
rule. The gap is the **latency budget itself** and confirming *every* listed
endpoint is capped.

**New work:**
- A load-test benchmark against the seeded library asserting **p95 < 500 ms**
  for the five read endpoints (series list, series detail, queue, history,
  wanted) — opt-in perf test.
- An always-on **cap audit**: each of the five endpoints returns a **paged
  envelope** (never an unbounded array) with the server-enforced page-size cap,
  and the stats fields come from the aggregate query — a construction test that
  fails if a new endpoint ships uncapped.

---

## FRG-NFR-007 — crash-safe queues and idempotent work

**Already-satisfied mechanism/idempotency (reuse):** persisted command queue
surviving restart (FRG-SCHED-002), download-id join key (FRG-PP-003), the
tracked-download state machine, the import "already-registered → no-op" path
(`library_import.py` `all_already_registered`; the drain's equivalent), and the
blocklist dedup key carrying `pub_date` (FRG-DL-012). Much of this is already
tested. The missing M2 piece is the **end-to-end crash property** tagged to
NFR-007.

**New work — staged fault injection (kill points → restart):**
1. **Post-enqueue:** a command persisted `queued`/`started` at simulated crash is
   recovered on restart (re-queued), no acknowledged item lost.
2. **Mid-download:** re-running a snatch with the same **release guid /
   download id** creates no duplicate grab/tracked-download row (idempotent
   handler on the dedup key).
3. **Pre-import-commit:** re-running import of an already-registered file (same
   path) is a no-op — **no duplicate `issue_files` row** — exercising the
   already-imported path.
The heavy real-process `kill -9` matrix is the opt-in soak variant; the
CI-default asserts the same invariants by re-invoking handlers at the staged
points (the idempotency is what makes both equivalent).

---

## Work-area partition (file ownership → parallelism)

Detailed in `tasks.md`. Summary of the single-writer split and the
subtle-vs-mechanical judgment for the orchestrator:

- **Area 1 — HTTP listener limits + all new config keys** (owns `config.py`,
  `api/limits.py`, `api/__init__.py`). *Subtle* — streaming body cap, timeout
  scoped off WS, bounded rate limiter. Owns **every** new config key (incl. the
  `ws_*` ones) so `config.py` has one writer.
- **Area 2 — WS cap + inbound limits** (owns `ws/broadcast.py`, `ws/router.py`,
  `ws/__init__.py`). *Subtle* — must not regress the `0e0456a` lifecycle fix.
  **Consumes** Area 1's config keys (soft dependency: keys added first).
- **Area 3 — NFR budgets + import guard** (owns new test modules + the
  `importer` seam re-export). Splittable into 3a startup+import-seam (*subtle*:
  cycle reasoning), 3b scan benchmark (*mechanical*), 3c latency benchmark
  (*mechanical*), 3d crash fault-injection (*subtle*: fault points +
  idempotency). Distinct test files → parallel-safe.
- **Area 4 — docs / security / traceability / gate** (owns `docs/`, registry,
  matrix, merge). *Mechanical* except the security delta, which needs care.

## Open questions

- **Rate-cap default (240/1 s) and off-switch** — generous for a single admin;
  the `0`-disables escape hatch is the safety net if it ever bites the UI's
  React-Query fan-out. Confirm the number at review or leave `0`-default if the
  fan-out worries outweigh the DoS value.
- **HTTP timeout status code** — 503 vs 408 for a listener-side request timeout;
  503 chosen (server chose to abort), open to 408 if preferred for semantics.
- **Seam relocation vs. test-only** — the `IMPORT_FILE_MUTATION_GROUP` move is
  optional hardening; if review prefers minimal churn, the isolated-importability
  test alone is sufficient to guard the cycle and the relocation can be dropped.
