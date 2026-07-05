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
