# Change: m1-ui-opds-deploy — faces and shipping

## Why

Phase 3 change 7 of 7 core slices (approved plan, 2026-07-04). Changes 1-6 make a
headless system that acquires and organizes comics; this change gives it its faces —
the React UI in the Sonarr/Radarr design school (owner directive, 2026-07-04) and
the OPDS catalog the iPad reads from — and ships it as the linuxserver.io-convention
Docker image behind Tailscale. Completing this change completes M1.

## What Changes

Implements 18 approved baseline requirements (no new IDs; scenario elaboration only):

- **SPA shell (FRG-UI-001, 002)** — Vite + React + TypeScript; TanStack Query for
  ALL server state (query keys mirror API paths); one WebSocket-listener component
  mapping resource-change messages to cache invalidation/patches; design-token layer
  with theme-neutral names carrying the ant/foraging identity as accent
  color/logo/naming ONLY — layout language stays Sonarr/Radarr (dark left sidebar,
  toolbar-driven pages, poster/table views, overlay modals). The change-7 proposal
  includes a screen-by-screen mapping to Sonarr v3 equivalents; divergences are
  listed explicitly.
- **Screens (FRG-UI-003..009)** — library index (poster grid + table toggle, sort/
  filter); series detail (Sonarr-style issue table, per-issue monitored toggles,
  search buttons dispatching commands); add-series (lookup with plausibility
  annotations, add-options panel); queue (WS-live tracked downloads incl.
  import_pending/import_blocked with reasons); interactive search overlay showing
  EVERY decision with rejection reasons (the change-4 `/release` contract);
  settings: indexers + download clients — one generic schema-driven form renderer
  from `/schema` endpoints (secret fields write-only), test buttons wired to
  `/test`.
- **Push (FRG-API-010)** — WebSocket endpoint broadcasting debounced (~100ms)
  `{name, action, resource}` resource-change messages for series/issues/queue/
  commands, driven by the change-1 event bus; UI cache invalidation keyed on them.
- **OPDS (FRG-OPDS-001..006)** — OPDS 1.2 Atom catalog at a configurable base path:
  navigation root linking only non-empty shelves (M1 = All Series); per-series
  acquisition feeds built entirely from DB fields (zero archive I/O at feed time);
  library-id-only file resolution (path traversal unrepresentable — ids resolve
  via `issue_files` rows through safe_join); parameterized queries throughout;
  whole-file downloads with correct comic MIME types
  (`application/vnd.comicbook+zip` / `application/vnd.comicbook-rar`); feed
  pagination with OpenSearch totals; covers from the change-3 local cache.
- **Ship it (FRG-DEP-001, 011)** — single Docker image per linuxserver.io
  conventions (PUID/PGID, `/config` volume, s6-overlay-compatible init, TZ, port
  8789), frontend built into the image and served by the backend; HEALTHCHECK on
  `/health`; secret-scanned build; Tailscale-scoped exposure documented as the
  RISK-020 compensating control (no HTTPS termination — tailnet provides it).

## Capabilities

### New Capabilities

None — all requirements exist in the approved baseline specs.

### Modified Capabilities

- `ui`: FRG-UI-001..009
- `api`: FRG-API-010
- `opds`: FRG-OPDS-001..006
- `dep`: FRG-DEP-001, FRG-DEP-011

## Non-goals

- No history/wanted/blocklist/system screens, no manual-import overlay, no naming
  settings UI (all M2: FRG-UI-010..017); no calendar (B).
- No OPDS page streaming/OpenSearch/covers-in-feed beyond local cache links
  (FRG-OPDS-007..013, M2); no OPDS 2.0 ever (FRG-OPDS-015).
- No auth (M3) — OPDS and UI ship open on the tailnet per FRG-AUTH-001.
- No reader of any kind (permanent exclusion).

## Impact

- **New code**: `frontend/` (Vite app; vitest tests with FRG ids in test names —
  trace.py discovers `frontend/src/**/*.{test,spec}.*`); `backend/src/foragerr/
  opds/` + WS endpoint; `Dockerfile` + s6 init scripts + build workflow.
- **E2E**: this change's gate is the M1 acceptance: containerized add → search →
  grab (SAB or DDL) → import → browse → OPDS download, driven live.
- **Security**: OPDS is a new listener surface — RISK-001 (path traversal) closed
  by construction, RISK-002 (SQL injection) by parameterized queries + sort
  whitelists; W7 XML-escaping of untrusted values in feeds (FRG-NFR-012); risk
  register + STRIDE updated (FRG-PROC-006).
- **Registry**: on merge, the 18 rows flip `approved → implemented`.

## Approval

- **Approver:** Adrian
- **Date:** 2026-07-04
- **Decision:** Approved under the standing grant of 2026-07-04 covering changes
  3-7. Implementation may begin, scoped to the 18 requirements listed above.
