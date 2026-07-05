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
