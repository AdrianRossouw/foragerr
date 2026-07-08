# Changelog

All notable changes to foragerr are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project follows
Semantic Versioning per **FRG-PROC-013** (`openspec/specs/dev-process/spec.md`).

foragerr is a private project — never released publicly. These entries record the
tagged milestones on `main` for internal traceability and history. Each release is
also published as a GitHub Release carrying the same notes.

## [v0.3.1] — 2026-07-08

M3 change 3: OPDS page streaming (the reading upgrade).

### Added
- **OPDS-PSE page streaming**: PSE-capable readers (Panels, Chunky) can now open a
  comic and stream it **one page at a time** instead of downloading the whole file
  first. Every issue advertises page streaming **alongside** the existing whole-file
  download, so a non-streaming reader is unaffected. Pages stream in natural reading
  order and a reader can request a reduced width to save bandwidth (FRG-OPDS-008,
  FRG-OPDS-010).
- **Cached page counts**: an issue's page count is computed once at import (from the
  archive scan the pipeline already does — no extra work) and cached, so browsing the
  catalog stays fast and opens no archives at render time; a legacy issue's count is
  filled in on first access (FRG-OPDS-009).
- **Local covers with no external egress**: an issue with no ComicVine cover now shows
  a cover generated from its own first page (extracted, resized, cached), and all
  cover/thumbnail images are served by foragerr itself — your reader never reaches out
  to a third-party image host to show a cover (FRG-OPDS-011).

### Security
- The new server-side archive-open and image-decode paths (the only untrusted-archive
  decode surface on the OPDS listener) enforce configurable resource limits — archive
  member count, per-page decompressed size (checked before read), image pixel count
  (checked before decode; truncated-image loading disabled), a per-request time bound,
  and a bounded number of concurrent decodes — so a crafted zip-bomb or pixel-bomb in
  the library degrades to a bounded error instead of exhausting memory or CPU. RISK-005
  is closed and RISK-010's cover-extraction arm is live (FRG-OPDS-012).

### Notes
- **CBR (`.rar`) comics** are downloaded whole as before but are **not** page-streamed
  (foragerr does not bundle an unrar tool); keep a title as `.cbz` for streaming.
- New admin settings `opds_pse_max_members`, `opds_pse_max_page_bytes`,
  `opds_pse_max_pixels`, `opds_pse_max_width`, `opds_pse_request_timeout_seconds`
  (see the admin manual). Adds the **Pillow** image library (used only on these OPDS
  decode paths). Database migration 0012 adds `issue_files.page_count`. Gate: 8 review
  angles + Codex → fixes applied; backend 1569 passed / 10 skipped.

## [v0.3.0] — 2026-07-08

M3 change 1: weekly-pull backbone. **Begins milestone M3 ("comics-native")** — the
data, jobs, and read API beneath a weekly pull list (the screen itself is M3 change
2). Backend only; the external pull source is opt-in and off by default.

### Added
- Metadata-derived weekly release view: for a store-date week, the issues of watched
  series dated in that week, each with derived state (missing/wanted, downloading,
  downloaded, unmonitored) computed from issue + queue records — works with no
  external source configured (FRG-PULL-001).
- `GET /api/v1/pull?week=` read endpoint backing the view: standard paging envelope,
  per-entry match type and linked-issue state, prev/current/next week by parameter,
  read-only, no secret exposed (FRG-API-019).
- External weekly-pull source fetch (opt-in; `pull_enabled` off by default): the
  walksoftly / League-of-Comic-Geeks JSON API fetched over the hardened external
  egress profile (current + previous week, mandatory timeouts, auto-redirect
  disabled), parsed as untrusted JSON under byte caps; documented source codes
  handled (619 skips a week; 522/666/transport → a source-outage that leaves stored
  data intact and marks the source **degraded** in health) (FRG-PULL-002).
- Idempotent per-week storage: a `pull_entries` table with per-week
  replace-on-refresh, so a re-fetch is idempotent and a mid-run failure leaves the
  prior week intact; entries carry a link to a library issue and a match type, never
  their own wanted/downloaded status (FRG-PULL-003, migration 0011).
- Matching pull entries to the library: ComicVine-id match first (book-type guarded),
  else a guarded name match (normalized name/alias equal, 0 ≤ sequence delta < 3, and
  release date within the pull week ±2 days); ambiguous/unknown entries stay
  unmatched; an unmatched new #1/#0 is tagged as a new-series candidate. Only watched
  (monitored) series are matched (FRG-PULL-004).
- Refresh trigger for missing pulled issues: a matched-but-missing issue enqueues the
  existing `refresh-series` command (deduplicated on the queue), so metadata creates
  the issue and the series' monitor policy decides whether it becomes wanted — the
  pull side writes no issue status (FRG-PULL-005).
- Scheduled + manual pull refresh: a built-in `pull-refresh` task (default 4 h,
  clamped up to a 1 h floor) that fetches → stores → matches → triggers; a manual
  force-run bypasses the interval gate; runs recorded in history and pushed over the
  WebSocket (FRG-PULL-006).

### Security
- RISK-039 mitigation realised (timeouts, documented error-code handling,
  degraded-health, untrusted-JSON) and the pull-source arm of RISK-025 closed via the
  external egress profile (see the threat model and risk register).

Upgrade notes: new admin settings `pull_enabled` (default off), `pull_source_url`,
and `pull_refresh_interval_seconds` (see the admin manual "Weekly pull" section);
database migration 0011 adds the `pull_entries` table. Test status at merge:
backend 1513 passed / 10 skipped.

## [v0.2.8] — 2026-07-06

M2 change 6: hardening and performance. **Completes milestone M2 ("own your
library")** — v0.2.0..v0.2.8, 7 changes plus 2 owner-driven insertions.

### Added
- Listener resource limits: HTTP request body/header size caps (streamed and
  aborted at the cap, never buffered whole), request timeouts, and a per-client
  rate/concurrency cap; a WebSocket connection cap and inbound-frame size/rate
  limits on the drain loop (FRG-NFR-014, RISK-021 mitigated).
- Startup-time budget benchmark (5,000-issue seed, p95 over N starts) with a
  no-outbound-network-at-startup guard and an isolated-importability regression
  test (FRG-NFR-001).
- Scan-throughput benchmark (5,000 files under a 10-minute budget) and a UI-latency
  benchmark (p95 < 500 ms on key read endpoints), each with always-on structural
  guards (FRG-NFR-002, FRG-NFR-003).
- Crash-safe/idempotent-work fault-injection tests (kill-and-restart at
  post-enqueue, mid-download, and pre-import-commit) confirming no lost acknowledged
  item, no duplicate snatch, and no duplicate library rows (FRG-NFR-007).

### Security
- Request-sourced values written to structured logs are now bounded and
  CR/LF-sanitized, preventing a forged/injected log line (RISK-014, request arm).

Test status at merge: backend 1440/10, frontend 234, e2e 13+1 skipped, all green.

## [v0.2.7] — 2026-07-06

M2 change 5.5: config hygiene and first-run defaults.

### Changed
- Removed the three unused global credential fields (`dognzb_api_key`,
  `nzbsu_api_key`, `sabnzbd_api_key`) from settings; an existing config file that
  still carries them loads fine with a logged warning. Per-provider credentials are
  unaffected (FRG-DEP-003).

### Added
- ComicVine API key is now configurable from **Settings → General**: a masked field,
  a connectivity "Test" button, live apply without a restart, and honest reporting of
  whether the key is unset / set-in-file / set-by-environment (FRG-API-018,
  FRG-META-002, FRG-UI-020).
- Fresh installs now seed one enabled GetComics DDL indexer and one enabled built-in
  DDL download client, so a keyless search → grab → download pipeline works out of the
  box; an existing install is marked seeded without having providers injected
  (FRG-DEP-013).

Test status at merge: backend 1369/7, frontend 234, e2e 13+1 skipped, all green.

## [v0.2.6] — 2026-07-06

M2 change 5: ops, health, and backups.

### Added
- Scheduled database + config backups: full integrity check, WAL checkpoint, and a
  consistent SQLite-API backup (never a raw file copy) written to
  `/config/backups/scheduled-<timestamp>/`, with rolling retention; runnable on
  demand via "Back up now" (FRG-DB-009).
- Startup `PRAGMA quick_check` and a full `PRAGMA integrity_check` before every
  scheduled backup; a failure surfaces as a persistent health error and aborts the
  backup rather than overwriting the retained set (FRG-DB-012).
- Marker-driven startup restore: validate a chosen backup, snapshot the current
  database aside, swap the backup in, and clear the marker — all with the database
  closed (FRG-DB-010).
- `GET /api/v1/system/health`, `GET /api/v1/system/task`, and
  `POST /api/v1/system/task/{name}` (force-run), plus an extended
  `GET /api/v1/system/status` (FRG-API-014).
- System area in the UI: Status, Health (per-component state with remediation hints),
  and Tasks screens with per-task force-run (FRG-NFR-011, FRG-UI-016).

RISK-041 accepted (see risk register). Test status at merge: backend 1341/7,
frontend 221, e2e 13+1 skipped, all green.

## [v0.2.5] — 2026-07-06

M2 change 4.5: search autosuggest and quick-search.

### Added
- Bounded ComicVine "suggest" endpoint returning only the first page of results,
  distinct from the full paginated lookup (FRG-API-017).
- Add Series screen gains a debounced, cancellable autosuggest dropdown (fires after
  ≥3 characters) backed by the suggest endpoint (FRG-UI-005).
- Global header quick-search over locally cached series titles/aliases (no network
  request per keystroke), keyboard-navigable, with a "Search ComicVine for '…'"
  fall-through into Add Series (FRG-UI-019).

Also closes deferred e2e coverage for the History/Wanted/OPDS-Recent daily spine.
Test status at merge: backend 1298/7, frontend 204, e2e 13+1 skipped, all green.

## [v0.2.4] — 2026-07-06

M2 change 4: daily-use surfaces.

### Added
- History screen: single-source, deduplicated event feed over `import_history` with
  series/issue filters (FRG-API-011, FRG-UI-010).
- Wanted screen: paged missing-issues list with per-issue interactive search and a
  search-all action (FRG-API-012, FRG-UI-011).
- Blocklist screen: view blocked releases with the reason they were banned, and
  remove a release to make it grabbable again (FRG-UI-017).
- Root-folder management: `POST`/`DELETE /api/v1/rootfolder`, plus a Root Folders
  section in Media Management settings — previously a fresh install had no way to add
  a root folder at all, making series/download/import unreachable on first run
  (FRG-SER-008, FRG-UI-012).
- Delete-files support: series deletion with `deleteFiles=true` now actually deletes
  (routed through the recycle bin) instead of returning 501; new per-issue-file delete
  action (FRG-API-003, FRG-UI-004).
- OPDS Recent Additions feed and an OpenSearch-backed catalog search feed
  (FRG-OPDS-013, FRG-OPDS-007).

### Fixed
- An identical import-blocked outcome on retry no longer writes a duplicate history
  row each retry cycle (RISK-040, mitigated).
- The "started" command-status transition now pushes over the WebSocket like the
  queued/terminal transitions already did (FRG-SCHED-010).

### Changed
- The cutoff-unmet half of the Wanted requirement was dropped from this release per
  the owner's M2 reshape (quality cutoffs parked to backlog).

## [v0.2.3] — 2026-07-06

M2 change 3: existing-library import.

### Added
- Library Import screen: pick a root folder, scan it, review per-group ComicVine match
  proposals (confidence, poster, year, issue counts), correct via the existing lookup,
  then bulk-import — series are created with existing files already registered, no
  downloads triggered (FRG-IMP-023, FRG-UI-015).
- Root-folder scan gains junk-aware skipping (AppleDouble/`@eaDir`, resource forks,
  dotfiles, zero-byte files, unpack-temp folders) and DB-vs-disk reconciliation,
  generalized from the per-series rescan (FRG-IMP-022).
- Configurable duplicate-file arbitration: preferred-format-or-larger-size tie-break
  for same-rung duplicates (profile-order upgrades still decide first); fixed-release
  markers always win; the losing file can move to a dated duplicate-dump folder
  instead of being deleted (FRG-PP-014).

## [v0.2.2] — 2026-07-06

M2 defect fix: lookup auth-error surfacing.

### Fixed
- Add Series no longer silently shows an empty "no results" state when the ComicVine
  API key is missing or invalid; a distinct error state names the credential problem
  instead (FRG-META-004, FRG-API-003, FRG-UI-005).
- Lookup responses now expose `complete`/`truncated` flags so a degraded partial
  result, a capped result, and a clean empty result are distinguishable from one
  another.
- Re-running a search with the same term always issues a fresh lookup rather than
  reusing a stale error/result state.
- The add-series flow surfaces the same credential guidance (instead of a generic
  failure message) when the existence check hits a ComicVine auth error.

## [v0.2.1] — 2026-07-06

M2 change 2: manual import and ComicInfo metadata.

### Added
- Manual import: resolve candidate files (from an import-blocked download or an
  arbitrary folder) with per-file series/issue/format overrides, executed through the
  same pipeline, evidence layer, and safety rails as automatic import — no parallel
  code path (FRG-PP-016, FRG-API-015, FRG-UI-014).
- Embedded ComicInfo.xml (and embedded ComicVine issue ids) is read at import time and
  preferred as evidence over filename parsing when verified (FRG-IMP-024).
- Optional in-process ComicInfo.xml tagging of cbz archives on import, off by default,
  routed through the shared archive-safety layer (FRG-PP-017).

### Fixed
- WebSocket endpoint teardown no longer attempts to re-close a socket the client has
  already closed.

## [v0.2.0] — 2026-07-06

M2 change 1: naming control, rename preview, and recycle bin.

### Added
- Rename preview: compute existing-path → new-path previews for any series/file
  selection under the current naming templates, without touching disk; execution is
  an explicit second step (FRG-PP-012).
- Recycle bin: a configurable directory for upgrade-replaced files and user-initiated
  deletions, replacing M1's fixed quarantine folder, with retention pruning
  (FRG-PP-013).
- Settings → Media Management screen: file/folder naming templates with token help and
  a live rename preview against a real series (FRG-UI-012).
- Config resource endpoints backing the naming/media-management settings screen
  (FRG-API-013).

### Changed
- `config.yaml` gains a schema version; startup migrates older config files forward
  (with the same pre-migration backup discipline the database already had) and refuses
  newer-than-supported files (FRG-DEP-004).

## [v0.1.1] — 2026-07-06

M1 acceptance-certified. **Completes milestone M1** (acceptance sign-off recorded in
the archived change-8 proposal).

### Added
- Playwright end-to-end verification harness exercising the full M1 slice against the
  real container image, with external services mocked by default and optionally live
  via env-gated credentials: add a series, interactive search with rejection reasons,
  grab → download → automatic import → renamed file in the library, series browse in
  the UI, and OPDS feed navigation/download with correct MIME type (FRG-PROC-010).

### Changed
- The M1 acceptance layer is generated directly from FRG-tagged e2e results rather
  than a hand-authored criteria matrix: 8 pass / 1 skipped (live tier) / 0 flaky /
  0 not-run, rolling up 19 FRG requirements.

## [v0.1.0] — 2026-07-06

M1 feature-complete: the full vertical slice from filename parsing through metadata,
search, download, import, UI, and OPDS.

### Added
- Foundational backend: single SQLite database with WAL mode and forward-only
  migrations, a persisted background-command scheduler with priority/exclusivity
  groups and an in-process event bus, structured logging, an unauthenticated
  `/health` liveness endpoint, and a shared outbound HTTP client with SSRF egress
  controls (FRG-DB-001..008, FRG-SCHED-001..011, FRG-DEP-002,003,005..010,
  FRG-SEC-001).
- Deterministic filename parser: issue numbers (including decimals, suffixes, ranges),
  volumes, years, annuals/specials, and scan-group/edition tags, validated against a
  75-row corpus and ~4.6k real filenames (FRG-IMP-001..021).
- Library management: series/issue tracking keyed to ComicVine volume/issue ids,
  two-level (series and issue) monitoring, root folders with templated paths, format
  profiles, and ComicVine metadata refresh with rate limiting, offset pagination, and
  local cover-art caching (FRG-SER-001..014, FRG-META-001..014, FRG-QUAL-001..002).
- Newznab indexer support (RSS, automatic, and interactive search) with a decision
  engine that surfaces every accept/reject outcome and its reason, cross-indexer
  de-duplication, and hardened/defused XML parsing (FRG-IDX-001..010,
  FRG-SRCH-001..014, FRG-SEC-002).
- Downloading via SABnzbd and a built-in DDL client (GetComics), with a
  tracked-download state machine, automatic blocklisting, and re-search on failure
  (FRG-DL-001..013, FRG-DDL-001..013).
- Shared import pipeline: multi-source evidence aggregation, archive validity/safety
  checks (zip-slip protection, size/nesting caps), safe file operations, token-based
  renaming with a round-trip guarantee, and import history (FRG-PP-001..011,
  FRG-SEC-003..004).
- React + TypeScript web UI: library grid/table, series detail with per-issue
  monitoring, add-series lookup, a live (WebSocket-pushed) queue, an interactive search
  overlay showing every decision, and schema-driven provider settings forms
  (FRG-UI-001..009, FRG-API-010).
- OPDS 1.2 acquisition catalog for reading over Tailscale: navigation root, per-series
  feeds built entirely from database fields, library-id-only file resolution, correct
  comic MIME types, and paginated feeds (FRG-OPDS-001..006).
- Single linuxserver.io-convention Docker image (PUID/PGID, `/config` volume,
  s6-overlay-compatible init, HEALTHCHECK, port 8789) with the frontend built in and
  served by the backend (FRG-DEP-001, FRG-DEP-011).

### Security
- No authentication on any surface by design, with the risk explicitly accepted and
  documented (RISK-020); the deployment model is Tailscale-only exposure with no
  built-in HTTPS termination (FRG-AUTH-001).
