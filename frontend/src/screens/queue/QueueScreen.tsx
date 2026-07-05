import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Toolbar } from '../../components/Toolbar';
import { useQueuePage } from '../../api/hooks';
import { queryKeys } from '../../api/queryKeys';
import type { QueueItem } from '../../api/types';
import { formatBytes, formatEta } from '../../utils/format';
import { QueueStatusChip } from './QueueStatusChip';
import { RemoveQueueDialog } from './RemoveQueueDialog';
import styles from './QueueScreen.module.css';

/**
 * Activity: Queue (FRG-UI-006) — Sonarr-shaped dense table over the tracked-
 * download queue. Rows live-update through the WebSocketBridge's queue-progress
 * patch (this screen only OBSERVES ['queue', page]; it never refetches on push),
 * and a row patched to imported/ignored leaves the table without a reload.
 */

/** States the queue never shows; a WS patch to one of these hides the row. */
const HIDDEN: ReadonlySet<QueueItem['status']> = new Set(['imported', 'ignored']);

export function QueueScreen() {
  const { data, isLoading, isError } = useQueuePage(1);
  const [removeTarget, setRemoveTarget] = useState<QueueItem | null>(null);
  const queryClient = useQueryClient();

  const items = (data ?? []).filter((item) => !HIDDEN.has(item.status));

  return (
    <>
      <Toolbar
        title="Queue"
        actions={
          <button
            type="button"
            className={styles.btn}
            onClick={() =>
              void queryClient.invalidateQueries({ queryKey: queryKeys.queue.all() })
            }
          >
            Refresh
          </button>
        }
      />
      <div>
        {isLoading && <p className={styles.state}>Loading queue…</p>}
        {isError && <p className={styles.state}>Could not load the queue.</p>}
        {!isLoading && !isError && items.length === 0 && (
          <p className={styles.state}>The queue is empty.</p>
        )}
        {items.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Status</th>
                <th>Series</th>
                <th>Issue</th>
                <th>Title</th>
                <th>Protocol</th>
                <th>Indexer</th>
                <th>Progress</th>
                <th>Time Left</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <QueueRow
                  key={item.id}
                  item={item}
                  onRemove={() => setRemoveTarget(item)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
      {removeTarget && (
        <RemoveQueueDialog
          item={removeTarget}
          onClose={() => setRemoveTarget(null)}
        />
      )}
    </>
  );
}

function QueueRow({ item, onRemove }: { item: QueueItem; onRemove: () => void }) {
  return (
    <tr data-testid={`queue-row-${item.id}`}>
      <td>
        <QueueStatusChip item={item} />
      </td>
      <td className={styles.seriesCell}>{item.seriesTitle ?? '—'}</td>
      <td className={styles.numeric}>
        {item.issueNumber != null ? `#${item.issueNumber}` : '—'}
      </td>
      <td>{item.title}</td>
      <td className={styles.muted}>
        {item.protocol}
        {item.downloadClient ? ` · ${item.downloadClient}` : ''}
      </td>
      <td className={styles.muted}>{item.indexer ?? '—'}</td>
      <td className={styles.progressCell}>
        <div
          className={styles.progressTrack}
          role="progressbar"
          aria-valuenow={item.progress}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${item.title} progress`}
        >
          <div className={styles.progressFill} style={{ width: `${item.progress}%` }} />
          <span
            className={styles.progressLabel}
            data-testid={`queue-progress-${item.id}`}
          >
            {item.progress}%
          </span>
        </div>
        <span className={styles.progressSub}>
          {formatBytes(item.sizeLeft)} left of {formatBytes(item.size)}
        </span>
      </td>
      <td className={styles.numeric}>{formatEta(item.estimatedCompletion)}</td>
      <td>
        <button
          type="button"
          className={styles.btn}
          aria-label={`Remove ${item.title}`}
          onClick={onRemove}
        >
          ✕
        </button>
      </td>
    </tr>
  );
}
