# Tasks — m2-hardening-performance

Grouped into parallelizable work areas by file ownership. Area 1 owns
`config.py` + the HTTP listener middleware (and adds **all** new config keys,
including the `ws_*` ones, so `config.py` has a single writer). Area 2 owns
`ws/` and consumes Area 1's keys (soft dependency: keys land first). Area 3 owns
the NFR benchmark/guard test modules and the importer seam re-export. Area 4 owns
`docs/` + traceability + the merge gate. Every task cites its requirement IDs.
Testing: pytest `@pytest.mark.req("FRG-...")`; heavy budget/soak tests marked
opt-in (like the existing baseline-acceptance soaks) with a cheap always-on
guard alongside.

## 1. HTTP listener request limits + config keys (owns config.py, api/limits.py, api/__init__.py)

- [ ] 1.1 Add the new documented config keys to `foragerr/config.py` `Settings`
      (each a `Field` with a description so `render_documented_config` emits it):
      `listener_max_body_bytes` (default 8 MiB, floor 64 KiB),
      `listener_max_header_bytes` (default 16 KiB),
      `listener_request_timeout_seconds` (default 30, clamped) +
      `listener_rate_max_requests` (default 240, 0 disables) +
      `listener_rate_window_seconds` (default 1, clamped), and the WS keys
      `ws_max_connections` (default 32, floor 1), `ws_max_inbound_bytes`
      (default 4 KiB), `ws_max_inbound_messages_per_second` (default 10). Add the
      two interval-shaped keys to `INTERVAL_RANGES` for clamp-with-warning. Tests:
      the keys appear in `render_documented_config` output with defaults;
      out-of-range interval values clamp with a warning (FRG-NFR-009 path).
      [FRG-NFR-014]
- [ ] 1.2 `foragerr/api/limits.py`: listener middleware on the HTTP scope only.
      Body-size cap — 413 on `Content-Length` over cap AND streaming byte-count
      abort for chunked/absent/lying `Content-Length` (no whole-body buffer);
      header-size cap → bounded 4xx; request timeout via `asyncio.wait_for` →
      bounded response, worker released; per-client (peer-address) sliding-window
      rate cap with a bounded/LRU client table → 429 + `Retry-After`, `0`
      disables. Install in `register_api`. Tests: multi-GiB drip with omitted
      `Content-Length` rejected at the cap with no memory blow-up; oversize
      headers rejected; a hung handler aborts at the timeout; a burst 429s and
      the client table stays bounded; a normal small-JSON request is unaffected;
      the WS route is not subject to the request timeout. [FRG-NFR-014]
- [ ] 1.3 Request-field log sanitization: ensure any request-sourced value the
      listener writes to structured logs (incl. the middleware's own 413/429
      warnings) passes the FRG-NFR-012 control-character stripper. Tests: a
      request path/header carrying CR/LF appears in captured logs as one escaped
      field, never a forged line. [FRG-NFR-014]

## 2. WebSocket connection cap + inbound limits (owns ws/broadcast.py, ws/router.py, ws/__init__.py)

- [ ] 2.1 `ws/broadcast.py`: add `max_connections` to `WsBroadcaster` and a
      `try_connect()` returning `None` when `connection_count >= max_connections`
      (no lock — single event-loop thread), else registering exactly as
      `connect()` does. Tests: `try_connect` refuses at the cap and admits below
      it; refusal does not mutate the registry or drop any live connection.
      [FRG-NFR-014]
- [ ] 2.2 `ws/router.py`: refuse the over-cap handshake — `try_connect()` → on
      `None`, `await websocket.close(code=1013)` **before** `accept()` and return
      (no registration); the accepted-connection path (register-before-accept,
      pump, drain, existing teardown) is otherwise byte-identical. Enforce the
      inbound size + rate limits inside `_drain_incoming`: an inbound frame over
      `ws_max_inbound_bytes` or a burst over `ws_max_inbound_messages_per_second`
      logs once and returns with the **client-still-connected** disposition so
      the endpoint's existing `if not client_gone: await websocket.close()` path
      performs the (single) close — the `0e0456a` client-gone computation and the
      genuine-`WebSocketDisconnect` → `True` path are unchanged. Tests: the
      (cap+1)-th connection is refused cleanly while existing sockets keep
      receiving broadcasts; an oversize inbound frame closes only that socket
      (others unaffected); a `WebSocketDisconnect` still suppresses the server
      close (no regression / no double close). [FRG-NFR-014]
- [ ] 2.3 `ws/__init__.py`: pass the configured `ws_max_connections` /
      `ws_max_inbound_bytes` / `ws_max_inbound_messages_per_second` from settings
      into the `WsBroadcaster` and the endpoint. Tests: the broadcaster is
      constructed with the configured cap; default config yields the documented
      defaults. [FRG-NFR-014]

## 3. NFR budgets + import-cycle guard (owns new test modules + importer seam)

- [ ] 3.1 (subtle) Startup budget + import guard [FRG-NFR-001]:
      (a) timed ready-to-serve test against a seeded 5,000-issue DB at head
      schema — `/health` 200 + scheduler running within 15 s p95 (marked
      soak/perf); (b) a no-outbound-HTTP-during-startup guard (startup with
      unreachable CV/indexers still ready in budget; no startup hook awaits the
      shared factory); (c) an isolated-importability regression test importing
      each leaf module (`foragerr.importer`, `.importer.pipeline`,
      `.importer.sources`, `.library.flows`, `.library.flows.library_import`,
      `.library.flows.rename`, `.library.flows.rescan`, `.downloads`) as the sole
      entry point in a fresh subprocess. Relocate
      `IMPORT_FILE_MUTATION_GROUP` into a neutral importer leaf and re-export it
      unchanged from `foragerr.importer.__init__` (byte-identical public API);
      keep the deferred `foragerr.downloads` import in `sources.py`. [FRG-NFR-001]
- [ ] 3.2 (mechanical) Scan-throughput [FRG-NFR-002]: seeded 5,000-file
      benchmark (~200 series) completing the parse/reconcile/stage phase under
      10 min with a concurrent API smoke inside the NFR-003 budget (marked
      soak/perf); plus an always-on structural guard asserting the scan command
      is `workload_class == "pp"`, the walk/existence-sweep run through `offload`
      (not the event loop) with no read-blocking exclusivity, and the measured
      phase issues no outbound HTTP. [FRG-NFR-002]
- [ ] 3.3 (mechanical) UI-latency [FRG-NFR-003]: load-test benchmark asserting
      p95 < 500 ms for the series-list, series-detail, queue, history, and wanted
      read endpoints against the seeded library (marked perf); plus an always-on
      cap audit — each returns a paged envelope with the page size clamped to the
      server-side cap (never unbounded) and stats come from a SQL aggregate.
      [FRG-NFR-003]
- [ ] 3.4 (subtle) Crash-safety fault-injection [FRG-NFR-007]: staged
      kill/restart acceptance — (a) a `queued`/`started` command is recovered on
      restart (no acknowledged item lost); (b) re-snatching the same release
      guid / download id creates no duplicate grab/tracked-download row; (c)
      re-importing an already-registered file path creates no duplicate
      `issue_files` row. CI-default re-invokes handlers at the staged points; the
      real-process kill matrix is the opt-in soak variant. [FRG-NFR-007]

## 4. Docs, security, traceability, gate

- [ ] 4.1 Security (FRG-PROC-006): flip **RISK-021** in
      `docs/security/risk-register.md` to **Mitigate (implemented)** with an
      m2-hardening status note (WS concurrent-connection cap + inbound-frame
      size/rate limits landed; HTTP body/header/timeout + per-client rate caps
      landed; the M1 documented latent is closed). Add an m2-hardening note to
      **RISK-014** recording that the CR/LF log-forging residual is now closed
      for request-sourced fields at the listener (the DDL scraped-text arm is
      unchanged, still tracked). Update `docs/security/threat-model.md`: the G-1
      listener note (§interfaces) and the COMP 2 WebSocket documented-latent move
      to their mitigated state. [FRG-PROC-006]
- [ ] 4.2 Manual (FRG-PROC-011): `docs/manual/admin/configuration.md` — document
      the new listener/WS limit settings (max body size, header size, request
      timeout, per-client rate cap + its 0-disables safety-valve note; WS max
      connections + inbound-frame size/rate), with defaults and floors. No other
      manual section changes (the NFR budgets are internal quality gates). [FRG-PROC-011]
- [ ] 4.3 Registry flips (FRG-NFR-001, FRG-NFR-002, FRG-NFR-003, FRG-NFR-007,
      FRG-NFR-014 → implemented) + matrix regen (`tools/trace.py` exit 0);
      `tools/soup_check.py` exit 0 (no SOUP change expected — if a dependency is
      added, update `docs/security/soup-register.md` in this change).
      [FRG-PROC-004, FRG-PROC-005, FRG-PROC-012]
- [ ] 4.4 Suites green (backend + any perf/soak marked runs exercised once);
      review gate (8-angle + Codex); fixes; `--no-ff` merge; main suites green;
      tag the release per FRG-PROC-013. [FRG-PROC-007]
