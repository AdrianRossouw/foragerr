import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Toolbar } from '../../components/Toolbar';
import { useQueuePage } from '../../api/hooks';
import { queryKeys } from '../../api/queryKeys';
import type { QueueItem } from '../../api/types';
import { formatBytes, formatEta } from '../../lib/format';
import { QueueStatusChip } from './QueueStatusChip';
import { RemoveQueueDialog } from './RemoveQueueDialog';
import { ManualImportOverlay } from './ManualImportOverlay';
import type { ManualImportSource } from './manualImportHooks';
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
  // The manual-import overlay's single source: a blocked download (from a row
  // action) OR a managed folder path (from the toolbar path picker).
  const [manualSource, setManualSource] = useState<ManualImportSource | null>(null);
  const [manualTitle, setManualTitle] = useState<string | undefined>(undefined);
  const queryClient = useQueryClient();

  const items = (data ?? []).filter((item) => !HIDDEN.has(item.status));

  const openManualForDownload = (item: QueueItem) => {
    setManualSource({ kind: 'download', downloadId: item.downloadId });
    setManualTitle(item.seriesTitle ?? item.title);
  };
  const openManualForPath = (path: string) => {
    setManualSource({ kind: 'path', path });
    setManualTitle(path);
  };
  const closeManual = () => {
    setManualSource(null);
    setManualTitle(undefined);
  };

  return (
    <>
      <Toolbar
        title="Queue"
        actions={
          <>
            <ManualImportPathPicker onLoad={openManualForPath} />
            <button
              type="button"
              className={styles.btn}
              onClick={() =>
                void queryClient.invalidateQueries({ queryKey: queryKeys.queue.all() })
              }
            >
              Refresh
            </button>
          </>
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
                  onManualImport={() => openManualForDownload(item)}
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
      {manualSource && (
        <ManualImportOverlay
          source={manualSource}
          contextTitle={manualTitle}
          onClose={closeManual}
        />
      )}
    </>
  );
}

/**
 * Toolbar path picker (FRG-UI-014): no filesystem browser exists, so manual
 * import from an arbitrary managed folder is a plain absolute-path input + Load.
 */
function ManualImportPathPicker({ onLoad }: { onLoad: (path: string) => void }) {
  const [path, setPath] = useState('');
  const submit = () => {
    const trimmed = path.trim();
    if (trimmed) onLoad(trimmed);
  };
  return (
    <form
      className={styles.pathPicker}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <input
        type="text"
        className={styles.pathInput}
        placeholder="/absolute/folder/path"
        aria-label="Manual import folder path"
        value={path}
        onChange={(e) => setPath(e.target.value)}
      />
      <button type="submit" className={styles.btn} disabled={path.trim() === ''}>
        Manual import
      </button>
    </form>
  );
}

function QueueRow({
  item,
  onRemove,
  onManualImport,
}: {
  item: QueueItem;
  onRemove: () => void;
  onManualImport: () => void;
}) {
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
      <td className={styles.actionsCell}>
        {item.status === 'import_blocked' && (
          <button
            type="button"
            className={styles.btn}
            aria-label={`Manual import ${item.title}`}
            onClick={onManualImport}
          >
            Manual import
          </button>
        )}
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
