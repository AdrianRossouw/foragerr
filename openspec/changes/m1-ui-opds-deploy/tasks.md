# Tasks

## 1. WebSocket push (worktree area: ws)

- [ ] 1.1 `/api/v1/ws` endpoint: event-bus subscriber, ~100ms (name, action) debounce/batching, per-socket send queues with slow-client drop, series/issues/queue/commands coverage (FRG-API-010)
- [ ] 1.2 Tagged tests: push-without-poll, burst coalescing, slow-client isolation, reconnect resumption (FRG-API-010)

## 2. OPDS (worktree area: opds)

- [ ] 2.1 Atom builder + per-feed routes (root, series shelf, series acquisition) at configurable base path; non-empty-shelf rule; XML escaping of all values (FRG-OPDS-001, FRG-OPDS-002)
- [ ] 2.2 File route `/opds/file/{issue_file_id}`: id-only resolution → safe_join check → FileResponse with comic MIME map + Content-Disposition; unknown/foreign id → 404 (FRG-OPDS-003, FRG-OPDS-005)
- [ ] 2.3 Pagination with Atom nav links + OpenSearch totals + per-page cap; same-feed link regression test (FRG-OPDS-006)
- [ ] 2.4 Tagged tests: zero-archive-I/O instrumentation, no-interpolated-SQL static check, injection payloads inert, traversal unrepresentable (route-table inventory), byte-identical downloads with exact MIME (FRG-OPDS-001..006)

## 3. Frontend (worktree area: frontend)

- [ ] 3.1 Vite + React + TS scaffold; tokens.css (theme-neutral names, Sonarr-dark values, ant accent) + token-name audit test; app shell (dark left sidebar, toolbar frame) (FRG-UI-002)
- [ ] 3.2 Query layer: TanStack Query with path-mirroring keys; WebSocketBridge (invalidation + queue patch, reconnect/backoff, sidebar state) (FRG-UI-001)
- [ ] 3.3 Library index: poster grid/table toggle, sort/filter, local covers (FRG-UI-003)
- [ ] 3.4 Series detail: banner + toolbar commands + issue table (string issue numbers, per-row/bulk monitor, search buttons) (FRG-UI-004)
- [ ] 3.5 Add series: lookup with plausibility annotations, add-options panel, add → detail with live refresh command (FRG-UI-005)
- [ ] 3.6 Queue screen: WS-live rows, import_pending/blocked reason popovers, remove dialog with blocklist option (FRG-UI-006)
- [ ] 3.7 Interactive search overlay: all decisions with verbatim reasons in comparator order, grab via cache key, expired-cache error (FRG-UI-007)
- [ ] 3.8 Generic schema-form renderer + indexer settings (cards, modal, widget map, write-only secrets, test button) (FRG-UI-008)
- [ ] 3.9 Download-client settings on the SAME renderer with zero new form code (audit test) (FRG-UI-009)
- [ ] 3.10 Vitest suites with FRG ids in test names for every UI requirement (FRG-UI-001..009)

## 4. Ship it (worktree area: deploy)

- [ ] 4.1 Multi-stage Dockerfile (frontend build → python-slim + uv + static serve), PUID/PGID s6-compatible init, TZ, EXPOSE 8789, HEALTHCHECK; build script with secret scan (FRG-DEP-001)
- [ ] 4.2 `docs/deploy.md`: Tailscale-only exposure as RISK-020 control, tailnet-bound compose example, do-not-port-forward warning (FRG-DEP-011)
- [ ] 4.3 Container tests: PUID ownership, /config persistence across recreate, healthcheck (FRG-DEP-001)

## 5. M1 acceptance, security docs, merge gate

- [ ] 5.1 E2E script: compose (foragerr + fixture SAB + fixture indexer); add → interactive search (rejections visible) → grab (DDL fixture) → import (renamed file) → UI browse smoke → OPDS download MIME+bytes (FRG-DEP-001, FRG-UI-001..009, FRG-OPDS-005)
- [ ] 5.2 Risk register: RISK-001/002 closed-by-construction status; WS-Origin M3 residual note; STRIDE delta for WS/OPDS/static listeners (FRG-PROC-006)
- [ ] 5.3 All 18 ids tagged-tested; registry flip; trace.py exit 0; suite green → /code-review → /simplify → merge --no-ff → archive → decision-index update (FRG-PROC-004, FRG-PROC-005, FRG-PROC-007)
