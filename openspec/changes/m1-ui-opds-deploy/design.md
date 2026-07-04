# Design: m1-ui-opds-deploy

## Context

Final M1 change: React UI (owner directive: stay in the Sonarr/Radarr design school —
"keep it as close as sensible"), OPDS 1.2 catalog, WebSocket push, and the
linuxserver.io Docker image. Everything consumes changes 1-6's API surface; no new
domain behavior. The `.reference/` Sonarr clone is UX-study-only (no code imports —
Sonarr frontend is GPL; we reimplement, never copy).

## Goals / Non-Goals

**Goals:** the M1 acceptance flow demo-able end-to-end in a container: add → search →
grab → import → browse → OPDS read, with the UI feeling like home to a Sonarr user.

**Non-Goals:** M2 screens (history/wanted/manual-import/blocklist/system/naming),
OPDS-PSE/OpenSearch (M2), auth (M3), any reader.

## Decisions

1. **Screen-by-screen Sonarr v3 mapping** (owner-approval anchor):
   - Library index ← Sonarr Series index: dark left sidebar (Library / Activity /
     Settings / System groups), top toolbar (view toggle poster/table, sort, filter),
     poster grid with hover overlays + table view with sortable columns
     (title/count/have/profile/path).
   - Series detail ← Sonarr series page: banner header (cover, monitored toggle,
     profile, path, stats), toolbar actions (Refresh, Rescan, Search Monitored —
     all `POST /command`), issue table (monitor toggle per row, issue number TEXT,
     cover date, have/file info, per-issue interactive-search button).
   - Add series ← Sonarr Add New: search box → CV candidate cards (poster, year,
     publisher, plausibility annotations from change 3) → add panel (root folder,
     profile, monitor strategy, search-on-add toggle).
   - Queue ← Sonarr Activity/Queue: table of tracked downloads (status chips incl.
     import_pending/import_blocked with reason popovers), progress, remove-with-
     blocklist-option dialog.
   - Interactive search ← Sonarr interactive search modal: full-width overlay table
     — decision chip (approved/rejected + reason list tooltip), source/indexer,
     title, size, age, score; grab button per approved row (cache-key POST).
   - Settings: Indexers + Download Clients ← Sonarr settings cards + modal forms —
     provider cards with enable toggles; add/edit modal rendered 100% from
     `/schema` (field metadata → widget map: text/number/select/checkbox/password),
     test button wired to `/test`, secrets write-only placeholders.
   Divergences (explicit): no seasons layer anywhere; format profile instead of
   quality profile; single-user no-auth (no login screens); ant/foraging accent
   token set (accent color, logo, name) on the Sonarr-shaped shell.

2. **Frontend architecture** (FRG-UI-001/002): Vite + React 18 + TS strict;
   TanStack Query with query keys mirroring API paths (`['series']`,
   `['series', id]`, `['queue', page]`, `['release', issueId]`); mutations
   invalidate optimistically. One `<WebSocketBridge>` component: connects to
   `/api/v1/ws`, maps `{name, action, resource}` → query invalidation/patch;
   reconnect with backoff; connection state surfaced in the sidebar footer.
   Design tokens in `src/theme/tokens.css` (`--color-accent`, `--surface-*`,
   `--spacing-*` — theme-neutral names); Sonarr-dark default values; ant accent.
   No component library lock-in: headless primitives (Radix) + custom CSS mirroring
   the Sonarr look — avoids fighting a kit to match the school.
   Vitest + Testing Library; FRG ids in test names (trace.py discovery).

3. **WebSocket push** (FRG-API-010): backend `/api/v1/ws` endpoint; event-bus
   subscriber batches resource-change events, debounces ~100ms per (name, action),
   broadcasts JSON `{name, action, resource}`; connection registry with per-socket
   send queues (slow client → drop + close, never blocks the bus); M1 coverage:
   series, issues, queue, commands. No auth (M1; Origin validation is FRG-SEC-005,
   M3 — recorded residual).

4. **OPDS** (`opds/router.py`, FRG-OPDS-001..006): mounted at `/opds` (configurable
   base path); per-feed routes (`/opds`, `/opds/series`, `/opds/series/{id}`,
   `/opds/file/{issue_file_id}`) — deliberate divergence from Mylar's `?cmd=`
   dispatch. Feeds rendered with a small Atom builder over DB rows only (series
   title/count, issue title/date/size — all sanitized fields; XML-escaped via the
   builder, W7); zero archive I/O at render. File resolution strictly
   `issue_file_id → issue_files.path → safe_join check → FileResponse` with MIME
   from extension map (`application/vnd.comicbook+zip|rar`, `application/pdf`) —
   no client-supplied paths anywhere in the surface (FRG-OPDS-003 by construction).
   Pagination: `?page=` with Atom next/prev/first/last links + OpenSearch
   totalResults/itemsPerPage/startIndex. Covers linked from the local cache
   endpoint. Repository queries are SQLAlchemy-parameterized throughout
   (FRG-OPDS-004; grep-test asserts no textual SQL interpolation in opds/).

5. **Docker image** (FRG-DEP-001/011): multi-stage Dockerfile — stage 1 builds the
   frontend (node), stage 2 python-slim with uv-installed backend + static frontend
   served by FastAPI (`/` → SPA, `/api`, `/opds`, `/health`); linuxserver-style
   PUID/PGID via s6-overlay-compatible init scripts (drop-privileges exec), TZ env,
   single `/config` volume, EXPOSE 8789, HEALTHCHECK curl `/health`. Image build in
   CI-shape script (`tools/build-image.sh`) with a secret-scan step over the build
   context (FRG-DEP-005 CI half). Tailscale exposure doc (`docs/deploy.md`):
   compose example bound to the tailnet interface, RISK-020 restated, explicit
   "do not port-forward this" warning.

6. **E2E acceptance** (gate for the change): compose file with foragerr +
   fixture-SAB + fixture-indexer containers; scripted flow (docker build/run,
   add series against recorded CV fixtures via env-gated live key, interactive
   search shows rejections, grab via DDL fixture, import lands renamed file,
   OPDS client fetch asserts MIME + bytes). Full Playwright automation of the UI
   is change 8 — this change's E2E drives API + OPDS + one UI smoke.

## Risks / Trade-offs

- [Recreating Sonarr's look without its code] → tokens + a few core layout
  components get us "same school" not "pixel clone"; screen-mapping above is the
  acceptance anchor, reviewed against screenshots at the gate.
- [WS + React Query consistency] → invalidation (refetch) over patching for M1
  except queue progress (patch) — correctness first, optimization M2.
- [Slow OPDS clients on big libraries] → feed pagination mandatory + per-page cap;
  page streaming is M2.
- [s6-overlay complexity] → "s6-compatible" = PUID/PGID + init script contract,
  not full s6 supervision tree; documented divergence, revisit if linuxserver
  base-image adoption happens later.

## Migration Plan

No schema change. New listener surfaces (WS, OPDS, static) documented in STRIDE
delta. Rollback = don't merge.

## Open Questions

None blocking.
