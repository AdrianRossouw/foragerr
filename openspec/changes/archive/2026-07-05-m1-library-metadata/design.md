# Design: m1-library-metadata

## Context

Builds on change 1 (DB layer with `write_session()`, command backbone, event bus,
HTTP factory with `external` profile, config/secrets, API skeleton with error shape +
paging envelope) and change 2 (pure parser + shared normalization function). The
Sonarr-model behaviors here — derived wanted, two-level monitoring, add-chain,
refresh reconciliation — are the load-bearing domain semantics the whole product
copies (sonarr-architecture.md §1); the ComicVine client hardening rules come from
mylar-comicvine.md.

## Goals / Non-Goals

**Goals:** a populated, refreshable comic library driven entirely through the API:
lookup → add → refresh → scan → stats, with covers cached locally and the default
format profile seeded.

**Non-Goals:** search execution (change 4), any download/import behavior (5/6), UI
(7), scheduled refresh (B), unmatched-file import (change 6 owns FRG-SER-010).

## Decisions

1. **Domain model** (`library/models.py`, one Alembic migration):
   `root_folders` (id, path); `series` (id, cv_volume_id UNIQUE, title, sort_title,
   matching_key — from the change-2 shared normalization, publisher, start_year,
   status, monitored, monitor_new_items enum, format_profile_id FK, root_folder_id FK,
   path, cover_cached_at, added_at, refreshed_at, description_sanitized);
   `issues` (id, series_id FK ON DELETE CASCADE, cv_issue_id UNIQUE, issue_number
   TEXT, ordering_key — persisted from the change-2 ordering implementation,
   title, cover_date, store_date, monitored, added_at);
   `issue_files` (id, issue_id FK, path, size, added_at) — populated by scan here,
   consumed/extended by change 6;
   `format_profiles` (id, name UNIQUE, formats JSON ordered list, cutoff).
   All typed/sentinel-free per FRG-DB-008; issue numbers TEXT verbatim.

2. **Wanted is a query, not a column** (FRG-SER-004): a reusable SQLAlchemy selectable
   `wanted_issues()` = series.monitored AND issue.monitored AND released
   (cover/store date ≤ today) AND no issue_files row. Exposed as a repository
   function; no `wanted` column exists anywhere (schema test asserts this).

3. **Add flow as chained commands** (FRG-SER-005/006): `POST /api/v1/series` validates
   (CV volume exists via client, root folder exists, path template renders, no
   duplicate cv_volume_id), inserts the series row with `add_options`
   (monitor strategy: all/none/future/existing-missing…, search_on_add) persisted on
   the row, then enqueues `RefreshSeriesCommand(series_id)`. Refresh handler:
   fetch volume+issues → reconcile → apply add-time monitoring strategy once (then
   clear add_options) → enqueue `ScanSeriesCommand` → if search_on_add, enqueue
   `SeriesSearchCommand` (registered in change 4; until then registered as a
   recognized-but-inert stub so dedup/history semantics are real). Each step is a
   separate command on the backbone — restart-safe, visible in job history.

4. **Refresh reconciliation** (FRG-META-008): keyed by cv_issue_id —
   insert new (monitored per monitor_new_items policy, FRG-SER-007), update changed
   fields, delete local issues absent from CV **only when the issue fetch completed
   fully** (pagination incompleteness flag → skip delete arm, log, mark refresh
   partial). Issues with files are never hard-deleted (file rows preserved; issue kept
   with a warning flag). All inside one `write_session()`; SeriesRefreshed event after
   commit.

5. **ComicVine client** (`metadata/comicvine.py`): thin typed client over the
   change-1 `external` client — base `https://comicvine.gamespot.com/api`,
   `format=json`, `field_list` per endpoint, honest UA `foragerr/<version>`.
   API key from settings (SecretStr, auto-redacted); sent as query param but never
   logged (factory redaction covers it). Mapping functions return typed dataclasses
   with `None` for absent fields — no `'None'` strings, non-integer issue numbers
   preserved verbatim (FRG-META-005/006). Errors map to typed exceptions
   (auth/rate-limit/malformed/unavailable).

6. **Process-global rate limiter** (FRG-META-003/NFR-004): one asyncio token gate in
   the client module (default min-interval 2s, configurable with clamp), shared by
   every CV call site including cover fetches; 429/Retry-After → sleep the greater of
   Retry-After/backoff, flip a degraded flag surfaced via the health payload;
   concurrent callers queue on the gate (test asserts serialized wire times).

7. **Pagination** (FRG-META-004): offset walk with `number_of_total_results` cross-
   check; a failed page mid-walk returns results-so-far + `complete=False`; callers
   (reconciliation) honor the flag (no delete arm). No unbounded loops: hard page cap
   from settings.

8. **Series search + plausibility** (FRG-META-007, API-003): `GET /api/v1/series/lookup?term=`
   → CV volume search mapped with plausibility annotations (name similarity via the
   shared matching key, year proximity, publisher ignore-list filter from settings)
   — annotations ride the response for the future UI; no auto-pick.

9. **Cover cache** (FRG-META-013): `<config>/covers/<series_id>.jpg` fetched through
   the rate limiter + egress policy (CV image host allowlisted via config, not
   hardcoded), size-capped by the factory; API serves `/api/v1/series/{id}/cover`
   from disk only (no proxying); missing cover → deterministic 404, refresh re-fetches
   when CV image URL changed.

10. **Untrusted content** (FRG-META-014/NFR-012): one `sanitize_cv_text()` used at
    ingest for every CV string (strip HTML to text, collapse whitespace, length cap);
    series path segments built from a `safe_path_component()` (strip separators,
    reserved names, trailing dots/spaces) — never raw CV titles (RISK-019); API
    responses carry sanitized text only. Filesystem confinement beyond component
    sanitization (safe-join) is FRG-SEC-004, change 6 — path *construction* here uses
    components + the root folder, no user/CV-supplied absolute paths.

11. **Series paths** (FRG-SER-008): M1 template fixed as
    `{root}/{Series Title (safe)} ({start_year})` with the full token engine deferred
    to change 6's renaming engine (PP-009/010 own templating); series.path stored,
    editable via PUT with validation (must be under a registered root folder).
    Statistics (FRG-SER-009) are computed per request via aggregate query
    (issue/file/missing counts, size on disk) — never stored columns.

12. **Series delete** (FRG-SER-014): DELETE with `deleteFiles=false|true` (M1: false
    only removes rows — cascade issues/files rows, keep disk); `deleteFiles=true`
    returns 501 until the recycle-bin lands (M2, PP-013) — explicit, documented,
    tested; edit (PUT) covers monitored, monitor_new_items, format_profile_id,
    root/path move (path move = row update + directory rename via safe rename with
    rollback on failure).

13. **API surface** (FRG-API-003..006): routers `series.py`, `issues.py`,
    `commands.py`; series list/detail/POST/PUT/DELETE + `/series/lookup`; issue
    list (by seriesId, paged envelope + whitelisted sort keys) with PUT monitored and
    `PUT /issues/monitor` bulk body `{issueIds, monitored}`; `POST /api/v1/command`
    validates name against the registry, returns 201 command resource; GET by id +
    list. All error shapes via the change-1 conventions.

## Risks / Trade-offs

- [CV fixtures drift from the live API] → env-gated live smoke test
  (`FORAGERR_CV_LIVE=1`, key from `.env`) exercising lookup+volume+issues on one
  known volume; fixtures regenerated from its recorded traffic.
- [Reconciliation delete arm destroys data on CV hiccups] → partial-fetch guard +
  never-delete-with-files rule + all-or-nothing transaction; tests simulate partial
  pagination explicitly.
- [Rate limiter serializes all CV traffic] → intended (politeness); add-flow latency
  is acceptable at M1 scale; degraded flag keeps slowness observable.
- [Fixed path template] → deliberate M1 contraction; PP's token engine (change 6)
  supersedes it; series.path stored per-row so the template can change without
  breaking existing rows.

## Migration Plan

One forward migration adding the five tables + seed of the default format profile
(FRG-QUAL-002) as a data migration. Rollback = don't merge.

## Open Questions

None blocking.
