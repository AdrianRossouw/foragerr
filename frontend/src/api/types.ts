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
  statistics: SeriesStatisticsResource;
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

/** One row of GET /api/v1/rename?seriesId= — a file whose name WOULD change. */
export interface RenamePreviewEntry {
  issueFileId: number;
  issueId: number;
  existingPath: string;
  newPath: string;
}
