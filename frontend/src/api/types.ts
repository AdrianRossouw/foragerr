/*
 * Typed shapes for the server resources the SPA reads. These are the MINIMAL
 * fields the scaffold's data-access hooks and the WebSocketBridge need. The real
 * response contracts (changes 1-6) are not final, so screen work (FRG-UI-003..009)
 * will extend/replace these — deliberately kept small and honest here.
 */

/** Comic issue numbers are strings on purpose (e.g. "1.5", "1.MU"). */
export interface Series {
  id: number;
  title: string;
  monitored: boolean;
  haveCount: number;
  totalCount: number;
}

export interface Issue {
  id: number;
  issueNumber: string;
  monitored: boolean;
  hasFile: boolean;
}

export interface SeriesDetail extends Series {
  publisher: string;
  year: number;
  overview: string;
  issues: Issue[];
}

/**
 * Tracked-download lifecycle state — the backend's `TrackedDownloadState`
 * (FRG-DL-007) verbatim. Note the naming seam: the scaffold's WS queue-progress
 * contract calls this field `status`, while the backend queue resource carries
 * it as `state` (its `status` is the ok/warning/error rollup, `QueueItemHealth`
 * here). `toQueueItem` in api/queue.ts owns the mapping.
 */
export type QueueItemStatus =
  | 'downloading'
  | 'import_pending'
  | 'import_blocked'
  | 'importing'
  | 'imported'
  | 'failed_pending'
  | 'failed'
  | 'ignored';

/** The backend's ok/warning/error rollup (its `status` column). */
export type QueueItemHealth = 'ok' | 'warning' | 'error';

/** Normalized queue row the UI renders and the WebSocketBridge patches. */
export interface QueueItem {
  id: number;
  /** Display title: issue title when mapped, else the raw download id. */
  title: string;
  status: QueueItemStatus;
  /** 0..100, derived from size/sizeleft. */
  progress: number;
  size: number;
  sizeLeft: number;
  health: QueueItemHealth;
  seriesId: number | null;
  issueId: number | null;
  seriesTitle: string | null;
  issueNumber: string | null;
  /** Verbatim backend status messages (import_blocked reasons live here). */
  statusMessages: string[];
  protocol: string;
  downloadClient: string | null;
  indexer: string | null;
  estimatedCompletion: string | null;
  /** The download-client id — the manual-import overlay's `?downloadId=` key. */
  downloadId: string;
}

/** One `GET /api/v1/queue` record exactly as the backend serializes it. */
export interface QueueResourceRaw {
  id: number;
  seriesId: number | null;
  issueId: number | null;
  series: { id: number; title: string } | null;
  issue: { id: number; issueNumber: string | null; title: string | null } | null;
  size: number | null;
  sizeleft: number | null;
  /** ok | warning | error rollup. */
  status: string;
  /** Lifecycle state (TrackedDownloadState value). */
  state: string;
  statusMessages: string[];
  downloadId: string;
  protocol: string;
  downloadClient: string | null;
  indexer: string | null;
  outputPath: string | null;
  estimatedCompletion: string | null;
}

/** The `GET /api/v1/queue` paging envelope (FRG-API-002 shape). */
export interface QueuePageResponse {
  page: number;
  pageSize: number;
  sortKey: string;
  sortDirection: string;
  totalRecords: number;
  records: QueueResourceRaw[];
}

/**
 * One `GET /api/v1/release` decision row, field names verbatim from the
 * backend's ReleaseDecisionResource (FRG-API-008). `indexer_id` + `guid` is the
 * cache key a grab POSTs back. Row order is the decision comparator's — the UI
 * must never re-sort it, and `rejections` are verbatim user-visible reasons.
 */
export interface ReleaseDecision {
  indexer_id: number;
  guid: string;
  indexer_name: string;
  title: string;
  format: string | null;
  size_bytes: number | null;
  age_seconds: number | null;
  score: number;
  outcome: 'approved' | 'temporarily-rejected' | 'rejected';
  approved: boolean;
  rejections: string[];
}

/*
 * ---------------------------------------------------------------------------
 * Backend-true resource shapes (changes 3-5 API surface, snake_case fields —
 * ground truth: backend/src/foragerr/api/series.py, issues.py, command.py).
 * The library screens (FRG-UI-003..005) consume these; the minimal scaffold
 * types above remain only for the FRG-UI-001 architecture tests/placeholders.
 * ---------------------------------------------------------------------------
 */

/** Shared paging envelope (FRG-API-006). Only its OWN keys are camelCase. */
export interface ApiPage<T> {
  page: number;
  pageSize: number;
  sortKey: string;
  sortDirection: string;
  totalRecords: number;
  records: T[];
}

/** Per-series aggregate stats (FRG-SER-009), nested on every series resource. */
export interface SeriesStatisticsResource {
  issue_count: number;
  file_count: number;
  missing_count: number;
  size_on_disk: number;
  next_release_date: string | null;
  last_release_date: string | null;
}

export interface SeriesResource {
  id: number;
  cv_volume_id: number;
  title: string;
  sort_title: string;
  publisher: string | null;
  start_year: number | null;
  status: string;
  monitored: boolean;
  monitor_new_items: string;
  format_profile_id: number;
  root_folder_id: number;
  path: string;
  cover_cached_at: string | null;
  added_at: string;
  refreshed_at: string | null;
  description_sanitized: string | null;
  aliases: string[];
  /**
   * Franchise group this series belongs to (FRG-SER-016), or null when
   * ungrouped. Carried on the flat list so the grouped view can reconcile
   * members to full resources without a second per-series call (FRG-API-020).
   */
  series_group_id: number | null;
  /**
   * Collected-edition type (FRG-SER-018): `tpb`/`gn`/`hc`/`one_shot` marks a
   * collected edition; `null` is an ordinary single-issues run. Display-only
   * (FRG-UI-022) — it drives the book-type badge and the collected filter and
   * NEVER changes monitoring, actions, or the wanted machinery (FRG-SER-019).
   */
  booktype: 'tpb' | 'gn' | 'hc' | 'one_shot' | null;
  statistics: SeriesStatisticsResource;
}

/**
 * One member series inside a franchise-group projection (FRG-API-020). A lean
 * subset of `SeriesResource` — the aggregate `GET /series/groups` endpoint
 * omits per-series `statistics`/cover; the flat `GET /series` list carries the
 * full resource, so the grouped view joins members back by `id`.
 */
export interface SeriesGroupMember {
  id: number;
  cv_volume_id: number;
  title: string;
  sort_title: string;
  status: string;
  start_year: number | null;
  monitored: boolean;
  series_group_id: number | null;
}

/**
 * One `GET /api/v1/series/groups` record (FRG-API-020). A `group` is an
 * operator-visible franchise (successive runs of one title folded together);
 * an ungrouped series comes back as a singleton franchise (`kind:"series"`,
 * `id:null`, one member). The roll-up counts (`series_count`, `issue_count`,
 * `owned_count`) come straight from the bounded aggregate query — never the
 * per-series statistics path.
 */
export interface SeriesGroupResource {
  id: number | null;
  kind: 'group' | 'series';
  title: string;
  series_count: number;
  issue_count: number;
  owned_count: number;
  series: SeriesGroupMember[];
}

/**
 * Grouping override op on `PUT /api/v1/series/{id}` (FRG-SER-017). `reassign`
 * needs `series_group_id`; `rename` needs `title`; `detach`/`unlock` need
 * neither. Reassign/detach lock the series against auto-derivation; unlock
 * clears the lock so the next refresh re-derives.
 */
export interface SeriesGroupEditOp {
  action: 'reassign' | 'detach' | 'rename' | 'unlock';
  series_group_id?: number | null;
  title?: string;
}

export interface IssueFileResource {
  id: number;
  path: string;
  size: number;
}

export interface IssueResource {
  id: number;
  series_id: number;
  cv_issue_id: number;
  /** Verbatim string — NEVER numeric ("1.5"/"1.MU" render unchanged). */
  issue_number: string | null;
  title: string | null;
  cover_date: string | null;
  store_date: string | null;
  issue_type: string;
  monitored: boolean;
  added_at: string;
  has_file: boolean;
  file: IssueFileResource | null;
}

/**
 * Lookup envelope (FRG-API-003): the candidate records plus the pagination
 * walk's `complete` flag. A degraded ComicVine walk returns `complete=false`
 * so the UI can flag partial results instead of rendering plain "no results".
 * `truncated=true` means the deliberate result cap was hit (and implies
 * `complete=false`) — that outcome asks for a narrower term, not a retry.
 */
export interface LookupResponse {
  records: LookupCandidate[];
  complete: boolean;
  truncated: boolean;
}

/** ComicVine search candidate with plausibility annotations (FRG-META-007). */
export interface LookupCandidate {
  cv_volume_id: number;
  name: string | null;
  publisher: string | null;
  start_year: number | null;
  image_url: string | null;
  count_of_issues: number | null;
  name_similarity: number;
  year_proximity: number | null;
  target_issue_plausible: boolean | null;
  have_it: boolean;
}

/**
 * Suggest envelope (FRG-API-017): the bounded, first-page-only accelerator
 * behind the Add Series autosuggest dropdown (FRG-UI-005). Carries `complete`
 * (a clean single-page fetch vs. one degraded by a mid-fetch upstream
 * failure) but deliberately carries NO `truncated` flag — a suggest result is
 * definitionally partial, so a cap is not a signal-worthy truncation.
 */
export interface SuggestResponse {
  records: SuggestCandidate[];
  complete: boolean;
}

/**
 * ComicVine suggest candidate (FRG-API-017) — the cheap first-page shape.
 * Unlike `LookupCandidate` it carries no plausibility annotations (the
 * suggest endpoint MAY omit that scoring to stay cheap); `have_it` is
 * retained so an already-owned volume can still be marked in the dropdown.
 */
export interface SuggestCandidate {
  cv_volume_id: number;
  name: string | null;
  publisher: string | null;
  start_year: number | null;
  image_url: string | null;
  count_of_issues: number | null;
  have_it: boolean;
}

/**
 * Router navigation-state contract for arriving at the Add Series screen with a
 * prefilled term (FRG-UI-005 / FRG-UI-019) — the header quick-search
 * fall-through (`HeaderQuickSearch`) navigates to `/add` carrying this shape,
 * which `AddSeries` consumes to seed its input and debounced autosuggest. Lives
 * in this neutral shared-types module rather than a screen module so both the
 * producer (`HeaderQuickSearch`) and the consumer (`AddSeries`) import it
 * without a cross-screen dependency.
 */
export interface AddSeriesNavigationState {
  prefillTerm?: string;
}

/**
 * One `GET /api/v1/rootfolder` row (FRG-SER-008). `free_space` is filesystem
 * free bytes, or null when the path could not be stat'd.
 */
export interface RootFolderResource {
  id: number;
  path: string;
  free_space: number | null;
}

/** One `GET /api/v1/formatprofile` row (FRG-QUAL-001). */
export interface FormatProfileResource {
  id: number;
  name: string;
  formats: string[];
  cutoff: string;
}

/** Command backbone resource (FRG-API-002) — the fields the UI reads. */
export interface CommandResource {
  id: number;
  name: string;
  status: string;
  /** The enqueue payload (e.g. rename-series carries `{ series_id }`). */
  payload?: Record<string, unknown>;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: string | null;
  error: string | null;
}

/** Request body for POST /api/v1/series (write-only add options). */
export interface SeriesCreatePayload {
  cv_volume_id: number;
  root_folder_id: number;
  format_profile_id: number | null;
  monitor_strategy: string;
  monitor_new_items: string;
  search_on_add: boolean;
}

/** POST /api/v1/series response: the series plus its queued refresh command. */
export interface SeriesCreatedResource extends SeriesResource {
  refresh_command_id: number;
}

/** Request body for PUT /api/v1/series/{id}; omitted field = don't change. */
export interface SeriesEditPayload {
  monitored?: boolean;
  monitor_new_items?: string;
  format_profile_id?: number;
  root_folder_id?: number;
  path?: string;
  aliases?: string[];
  /** Franchise-grouping override op (FRG-SER-017); omitted = don't touch grouping. */
  group?: SeriesGroupEditOp;
}

/** Valid monitor strategies for the add flow (backend MONITOR_STRATEGIES). */
export const MONITOR_STRATEGIES = [
  'all',
  'none',
  'future',
  'missing',
  'existing',
  'first',
] as const;

/** Valid monitor-new-items policies (backend MONITOR_NEW_ITEMS_POLICIES). */
export const MONITOR_NEW_ITEMS_POLICIES = ['all', 'none'] as const;

/*
 * Config resource shapes (FRG-API-013) + naming tokens (FRG-UI-012). These
 * mirror the typed GET/PUT singletons the naming / media-management settings
 * page reads and writes; field NAMES are the backend settings names verbatim.
 */

/** GET/PUT /api/v1/config/naming. */
export interface NamingConfig {
  rename_enabled: boolean;
  file_naming_template: string;
  folder_naming_template: string;
  replace_illegal_characters: boolean;
}

/** GET/PUT /api/v1/config/mediamanagement. */
export interface MediaManagementConfig {
  import_transfer_mode: string;
  library_import_mode: string;
  recycle_bin_path: string;
  recycle_bin_retention_days: number;
  /** FRG-PP-014 duplicate handling: same-rung resolution + loser dump folder. */
  duplicate_constraint: string;
  duplicate_dump_path: string;
  /** FRG-IMP-023 library-import scan tuning: max ComicVine proposals per scan. */
  library_import_proposal_cap: number;
  /** Minimum name similarity (0..1) before a scan proposes a match itself. */
  library_import_similarity_floor: number;
}

/**
 * GET /api/v1/config/naming/tokens — the ONE shared token vocabulary the
 * renderer accepts (design decision 11). `aliases` maps every casefolded token
 * name to its canonical field key; `defaults` carries the default templates.
 */
export interface NamingTokens {
  aliases: Record<string, string>;
  defaults: Record<string, string>;
}

/**
 * GET/PUT /api/v1/config/general — the ComicVine credential settings resource
 * (FRG-API-018). The key VALUE never appears in either response; only its
 * configured status and source (`unset` | `file` | `environment`) do. When
 * `source` is `environment`, `FORAGERR_COMICVINE_API_KEY` outranks any
 * file/UI-written value, so the settings screen renders read-only instead of
 * a silently-shadowed editor.
 */
export type ComicVineKeySource = 'unset' | 'file' | 'environment';

export interface ComicVineConfig {
  comicvine_api_key: {
    configured: boolean;
    source: ComicVineKeySource;
  };
}

/** POST /api/v1/config/comicvine/test result (FRG-API-018) — never the key. */
export interface ComicVineTestResult {
  success: boolean;
  message: string;
}

/** One row of GET /api/v1/rename?seriesId= — a file whose name WOULD change. */
export interface RenamePreviewEntry {
  issueFileId: number;
  issueId: number;
  existingPath: string;
  newPath: string;
}

/*
 * Manual-import candidate shapes (FRG-API-015 / FRG-UI-014). The list endpoint
 * (GET /api/v1/manual-import?path= XOR ?downloadId=) computes each file's
 * would-be import verdict through the shared pipeline; the execute endpoint
 * (POST /api/v1/manual-import) takes operator-corrected mappings. Field NAMES
 * are the backend's camelCase JSON verbatim.
 */

/** The embedded-ComicInfo read summary for one candidate (FRG-IMP-024). */
export interface ManualImportEmbedded {
  comicInfoPresent: boolean;
  cvIssueId: number | null;
  /** True once the embedded cv_issue_id was matched to a known issue. */
  verified: boolean;
}

/** One candidate file's would-be verdict (GET /api/v1/manual-import). */
export interface ManualImportEntry {
  path: string;
  name: string;
  size: number;
  folder: string | null;
  approved: boolean;
  /** Verbatim rejection reasons, in the pipeline's order — never re-sorted. */
  rejections: string[];
  suggestedSeriesId: number | null;
  suggestedIssueId: number | null;
  format: string | null;
  embedded: ManualImportEmbedded;
}

/** One picked file's corrected mapping (POST /api/v1/manual-import body). */
export interface ManualImportFileSpec {
  path: string;
  seriesId?: number | null;
  issueId?: number | null;
  format?: string | null;
}

/** The archive formats the override select offers (backend ARCHIVE_EXTENSIONS). */
export const ARCHIVE_FORMATS = ['cbz', 'cbr', 'cb7', 'cbt', 'pdf'] as const;

/*
 * Library-import staging shapes (FRG-IMP-023 / FRG-UI-015). GET
 * /api/v1/library-import returns the persisted scan groups for one root folder
 * in the shared paging envelope. Field names are the backend's camelCase JSON
 * VERBATIM (the manual-import resource convention) — the contract is pinned,
 * so `LibraryImportGroup` types the wire shape directly.
 */

/*
 * Daily-surfaces resource shapes (m2-daily-surfaces: FRG-API-011/012 +
 * blocklist read API). All three ride the shared ApiPage envelope with nested
 * series/issue display objects; history and blocklist use the queue
 * resource's camelCase convention, while wanted records are snake_case per
 * the issues-API convention.
 */

/** The backend's import_history event vocabulary (importer/history.py). */
export const HISTORY_EVENT_TYPES = [
  'grabbed',
  'imported',
  'upgrade_replaced',
  'import_blocked',
  'import_failed',
  'download_failed',
  'file_deleted',
  'file_renamed',
  'comicinfo_tag_failed',
] as const;

export type HistoryEventType = (typeof HISTORY_EVENT_TYPES)[number];

/** One GET /api/v1/history record (FRG-API-011, queue-pattern camelCase). */
export interface HistoryRecord {
  id: number;
  /** Event vocabulary value; typed open so unknown future events still render. */
  eventType: string;
  sourceTitle: string | null;
  downloadId: string | null;
  date: string;
  /** The canonical per-event payload; `reasons` (when present) is the verbatim
   * rejection-reasons array — never re-sorted. */
  data: Record<string, unknown>;
  series: { id: number; title: string } | null;
  issue: { id: number; issueNumber: string | null; title: string | null } | null;
}

/**
 * One GET /api/v1/wanted/missing record (FRG-API-012): issue-shaped with a
 * nested series, snake_case per the issues-API resource convention (unlike
 * the camelCase history/blocklist records). Release date is derived
 * client-side as store_date ?? cover_date.
 */
export interface WantedIssueRecord {
  id: number;
  series_id: number;
  cv_issue_id: number;
  /** Verbatim string — NEVER numeric ("1.5"/"1.MU" render unchanged). */
  issue_number: string | null;
  title: string | null;
  cover_date: string | null;
  store_date: string | null;
  issue_type: string;
  monitored: boolean;
  series: { id: number; title: string } | null;
}

/** One GET /api/v1/blocklist record. `message` is the verbatim ban reason. */
export interface BlocklistRecord {
  id: number;
  sourceTitle: string | null;
  indexer: string | null;
  guid: string | null;
  downloadId: string | null;
  /** The ban timestamp. */
  date: string;
  message: string | null;
  protocol: string | null;
  series: { id: number; title: string } | null;
  issue: { id: number; issueNumber: string | null; title: string | null } | null;
}

/** POST /api/v1/blocklist/delete response — partial failure is reportable. */
export interface BlocklistBulkDeleteResult {
  deleted: number[];
  missing: number[];
}

/** DELETE /api/v1/issuefile/{id} response (FRG-API-003 / FRG-UI-004). */
export interface IssueFileDeleteResult {
  /** Recycle-bin destination path, or null when permanently deleted. */
  recycled: string | null;
}

/** Staging lifecycle of one scanned folder group (design decision 2). */
export type LibraryImportGroupState =
  | 'proposed'
  | 'confirmed'
  | 'no_match'
  | 'imported'
  | 'skipped';

/** One staged library-import group, exactly as the wire carries it. */
export interface LibraryImportGroup {
  id: number;
  /** The parser's normalized series-name grouping key. */
  matchingKey: string;
  /** Absolute folder the group's files live under. */
  folder: string;
  /** File entries; the API serves {path,name,size} objects. Only the count
   * and names are rendered, so entries are kept structural. */
  files: { path: string; name: string; size: number }[];
  /** Parse confidence, 0..1. */
  confidence: number;
  proposedCvVolumeId: number | null;
  confirmedCvVolumeId: number | null;
  state: LibraryImportGroupState;
  /** Proposal presentation fields (null when there is no match). */
  name: string | null;
  startYear: number | null;
  publisher: string | null;
  imageUrl: string | null;
  /** Verbatim per-file blocked reasons from the last execute — never re-sorted. */
  rejections: string[];
  /** Human outcome summary (no-match reason, "imported=N blocked=M", add
   * failure) — rendered verbatim on the group card when present. */
  message: string | null;
}

/*
 * System status / health / tasks (FRG-API-014, FRG-NFR-011, FRG-UI-016).
 * m2-ops-health-backups — the backend routers do not exist yet in this
 * worktree; these types are coded directly from the change's delta specs
 * (specs/api/spec.md, specs/ui/spec.md) and design.md decisions 6/8/9.
 */

/**
 * GET /api/v1/system/status response (FRG-API-014). EXTENDS the existing
 * `{version, commit, build_date}` fields (kept byte-for-byte) with runtime
 * info and managed `/config` paths only — never a secret (design decision 9).
 */
export interface SystemStatusResource {
  version: string;
  commit: string;
  build_date: string;
  config_dir: string;
  db_path: string;
  backups_dir: string;
  root_folder_count: number;
  uptime_seconds: number;
  python_version: string;
  os: string;
}

/** Health item severity, shared by the warnings list and per-component view. */
export type HealthStateType = 'ok' | 'warning' | 'error';

/**
 * One GET /api/v1/health warnings-list entry (FRG-API-014 design decision 5).
 * `remediationHint` is camelCase verbatim per the api delta spec's contract
 * note, even though most other envelopes in this API are snake_case.
 */
export interface HealthWarningItem {
  source: string;
  type: HealthStateType;
  message: string;
  remediationHint: string | null;
}

/** Per-component state for GET /api/v1/system/health (FRG-NFR-011). */
export type ComponentHealthState = 'ok' | 'degraded' | 'error';

/**
 * One GET /api/v1/system/health per-component row (design decision 6). A
 * `degraded` indexer/provider carries `disabled_until` (back-off countdown);
 * `database` reflects integrity + last-backup age instead. `component` is the
 * stable machine id (e.g. "indexer:3") the UI keys rows on; `label` is the
 * human-readable display name (e.g. "Indexer: DogNZB") to render.
 */
export interface SystemHealthComponent {
  component: string;
  label: string;
  state: ComponentHealthState;
  message: string | null;
  last_success: string | null;
  last_failure: string | null;
  disabled_until: string | null;
}

/**
 * One GET /api/v1/system/task row (design decision 8): `scheduler.status()`
 * enriched with the command name and a display label.
 */
export interface ScheduledTaskResource {
  name: string;
  command_name: string;
  label: string;
  interval_seconds: number;
  last_run: string | null;
  next_run: string | null;
}

/*
 * Log ring buffer (FRG-API-021, FRG-UI-024, m4-logs-viewer). GET /api/v1/log
 * rides the shared ApiPage envelope (newest-first: sortKey 'time',
 * sortDirection 'desc'); `level`/`logger` are pinned contract fields coded
 * directly from the change's design.md ahead of the parallel backend build.
 */

/** The backend's log-level vocabulary, low to high severity. */
export const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR'] as const;

export type LogLevel = (typeof LOG_LEVELS)[number];

/**
 * One GET /api/v1/log record: a single buffered, already-redacted log line
 * (design decision 3 — redaction happens before buffering, never at read
 * time). `message` is the formatted record, capped server-side.
 */
export interface LogRecordResource {
  time: string;
  level: LogLevel;
  logger: string;
  message: string;
}
