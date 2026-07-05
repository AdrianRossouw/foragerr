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

export type QueueItemStatus =
  | 'downloading'
  | 'import_pending'
  | 'import_blocked'
  | 'completed';

export interface QueueItem {
  id: number;
  title: string;
  status: QueueItemStatus;
  /** 0..100 */
  progress: number;
  size: number;
  sizeLeft: number;
}

export interface ReleaseDecision {
  cacheKey: string;
  indexer: string;
  title: string;
  size: number;
  ageDays: number;
  approved: boolean;
  score: number;
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
  name_similarity: number;
  year_proximity: number | null;
  target_issue_plausible: boolean | null;
  have_it: boolean;
}

/** Command backbone resource (FRG-API-002) — the fields the UI reads. */
export interface CommandResource {
  id: number;
  name: string;
  status: string;
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
