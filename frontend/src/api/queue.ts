import type {
  QueueItem,
  QueueItemHealth,
  QueueItemStatus,
  QueueResourceRaw,
} from './types';

/*
 * Queue-resource normalization (FRG-UI-006).
 *
 * The ONE seam where the backend's queue vocabulary meets the frontend's:
 *   backend `state`    -> frontend `status`   (lifecycle; the WS queue-progress
 *                                              contract also calls it `status`)
 *   backend `status`   -> frontend `health`   (ok/warning/error rollup)
 *   backend `sizeleft` -> frontend `sizeLeft`
 *   derived `progress` (0..100)               (the backend sends no progress
 *                                              field; WS patches overwrite it)
 */

const KNOWN_STATES: readonly QueueItemStatus[] = [
  'downloading',
  'import_pending',
  'import_blocked',
  'importing',
  'imported',
  'failed_pending',
  'failed',
  'ignored',
];

const KNOWN_HEALTH: readonly QueueItemHealth[] = ['ok', 'warning', 'error'];

function toStatus(state: string): QueueItemStatus {
  // An unknown state renders as import_blocked's sibling severity rather than
  // crashing — but the vocabulary is a shared enum, so this is belt-and-braces.
  return (KNOWN_STATES as readonly string[]).includes(state)
    ? (state as QueueItemStatus)
    : 'import_blocked';
}

function toHealth(status: string): QueueItemHealth {
  return (KNOWN_HEALTH as readonly string[]).includes(status)
    ? (status as QueueItemHealth)
    : 'warning';
}

/** Derive 0..100 progress from size/sizeleft; sizeless items report 0. */
export function deriveProgress(size: number | null, sizeleft: number | null): number {
  if (size == null || size <= 0 || sizeleft == null) return 0;
  return Math.min(100, Math.max(0, Math.round(((size - sizeleft) / size) * 100)));
}

/** Normalize one raw backend queue record into the row the UI renders. */
export function toQueueItem(raw: QueueResourceRaw): QueueItem {
  return {
    id: raw.id,
    title: raw.issue?.title ?? raw.downloadId,
    status: toStatus(raw.state),
    progress: deriveProgress(raw.size, raw.sizeleft),
    size: raw.size ?? 0,
    sizeLeft: raw.sizeleft ?? raw.size ?? 0,
    health: toHealth(raw.status),
    seriesId: raw.seriesId,
    issueId: raw.issueId,
    seriesTitle: raw.series?.title ?? null,
    issueNumber: raw.issue?.issueNumber ?? null,
    statusMessages: raw.statusMessages,
    protocol: raw.protocol,
    downloadClient: raw.downloadClient,
    indexer: raw.indexer,
    estimatedCompletion: raw.estimatedCompletion,
    downloadId: raw.downloadId,
  };
}
