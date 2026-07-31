import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Toolbar } from '../../components/Toolbar';
import { PageControls } from '../../components/PageControls';
import { useQueuePage, type QueueRemoveResult } from '../../api/hooks';
import { queryKeys } from '../../api/queryKeys';
import type { QueueItem } from '../../api/types';
import { formatBytes, formatEta } from '../../lib/format';
import { QueueStatusChip } from './QueueStatusChip';
import { RemoveQueueDialog, queueItemName } from './RemoveQueueDialog';
import { ManualImportOverlay } from './ManualImportOverlay';
import type { ManualImportSource } from './manualImportHooks';
import styles from './QueueScreen.module.css';

/**
 * Activity: Queue (FRG-UI-006) — Sonarr-shaped dense table over the tracked-
 * download queue. Rows live-update through the WebSocketBridge's queue-progress
 * patch (this screen only OBSERVES ['queue', page]; it never refetches on push),
 * and a row patched to imported/ignored leaves the table without a reload.
 * Cleanup is selection-based: the same remove dialog serves one row, a
 * selection, and Clear failed, and reports per-row what did not remove.
 */

/** States the queue never shows; a WS patch to one of these hides the row. */
const HIDDEN: ReadonlySet<QueueItem['status']> = new Set(['imported', 'ignored']);

/**
 * A row that has stopped moving. Its size/remaining are whatever the client
 * last reported, so a progress bar over them reads as live progress that is not
 * happening — the status chip and its reason carry the state instead.
 */
function isFailed(item: QueueItem): boolean {
  return item.status === 'failed';
}

export function QueueScreen() {
  const [page, setPage] = useState(1);
  const { data, isLoading, isError } = useQueuePage(page, setPage);
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const [removeTargets, setRemoveTargets] = useState<QueueItem[] | null>(null);
  const [notices, setNotices] = useState<string[]>([]);
  // The manual-import overlay's single source: a blocked download (from a row
  // action) OR a managed folder path (from the toolbar path picker).
  const [manualSource, setManualSource] = useState<ManualImportSource | null>(null);
  const [manualTitle, setManualTitle] = useState<string | undefined>(undefined);
  const queryClient = useQueryClient();

  const items = (data?.records ?? []).filter((item) => !HIDDEN.has(item.status));
  const selectedItems = items.filter((item) => selected.has(item.id));
  const failedItems = items.filter(isFailed);
  const allSelected = items.length > 0 && selectedItems.length === items.length;

  const toggleSelected = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const toggleSelectAll = () => {
    setSelected(allSelected ? new Set() : new Set(items.map((item) => item.id)));
  };

  const clearFailed = () => {
    // Selection sugar: the same dialog, the same removal — Clear failed only
    // decides WHICH rows are named, never how they are removed.
    setSelected(new Set(failedItems.map((item) => item.id)));
    setRemoveTargets(failedItems);
  };

  /** Report what did NOT remove, and leave exactly those rows selected. */
  const reportOutcome = (targets: QueueItem[], result: QueueRemoveResult) => {
    const nameById = new Map(targets.map((item) => [item.id, queueItemName(item)]));
    const failures = Object.entries(result.errors);
    setNotices(
      failures.map(
        ([id, reason]) => `${nameById.get(Number(id)) ?? `Item ${id}`}: ${reason}`,
      ),
    );
    setSelected(new Set(failures.map(([id]) => Number(id))));
  };

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
          <span className={styles.toolbarActions}>
            <ManualImportPathPicker onLoad={openManualForPath} />
            <button
              type="button"
              className={styles.btn}
              disabled={failedItems.length === 0}
              onClick={clearFailed}
            >
              Clear failed
            </button>
            <button
              type="button"
              className={styles.btn}
              onClick={() =>
                void queryClient.invalidateQueries({ queryKey: queryKeys.queue.all() })
              }
            >
              Refresh
            </button>
          </span>
        }
      />
      <div>
        {notices.length > 0 && (
          <div className={styles.notice} role="alert">
            Some items could not be removed:
            <ul className={styles.noticeList}>
              {notices.map((notice) => (
                <li key={notice}>{notice}</li>
              ))}
            </ul>
          </div>
        )}
        {selectedItems.length > 0 && (
          <div className={styles.bulkBar}>
            <span className={styles.bulkCount} data-testid="queue-selection-count">
              {selectedItems.length} selected
            </span>
            <button
              type="button"
              className={styles.btn}
              onClick={() => setRemoveTargets(selectedItems)}
            >
              Remove selected
            </button>
          </div>
        )}
        {isLoading && <p className={styles.state}>Loading queue…</p>}
        {isError && <p className={styles.state}>Could not load the queue.</p>}
        {!isLoading && !isError && items.length === 0 && (
          <p className={styles.state}>The queue is empty.</p>
        )}
        {items.length > 0 && (
          <div className={styles.tableWrap} data-testid="queue-table-wrap">
            <table className={styles.table}>
              <thead>
                <tr>
                  <th className={styles.selectCol}>
                    <input
                      type="checkbox"
                      aria-label="Select all queue items"
                      checked={allSelected}
                      onChange={toggleSelectAll}
                    />
                  </th>
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
                    selected={selected.has(item.id)}
                    onToggleSelected={() => toggleSelected(item.id)}
                    onRemove={() => setRemoveTargets([item])}
                    onManualImport={() => openManualForDownload(item)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && (
          <PageControls
            page={data.page}
            totalRecords={data.totalRecords}
            pageSize={data.pageSize}
            onPageChange={setPage}
          />
        )}
      </div>
      {removeTargets && (
        <RemoveQueueDialog
          items={removeTargets}
          onClose={() => setRemoveTargets(null)}
          onRemoved={(result) => reportOutcome(removeTargets, result)}
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
  selected,
  onToggleSelected,
  onRemove,
  onManualImport,
}: {
  item: QueueItem;
  selected: boolean;
  onToggleSelected: () => void;
  onRemove: () => void;
  onManualImport: () => void;
}) {
  const failed = isFailed(item);
  return (
    <tr data-testid={`queue-row-${item.id}`}>
      <td className={styles.selectCol}>
        <input
          type="checkbox"
          aria-label={`Select ${item.title}`}
          checked={selected}
          onChange={onToggleSelected}
        />
      </td>
      <td>
        <QueueStatusChip item={item} />
      </td>
      <td className={styles.seriesCell}>{item.seriesTitle ?? '—'}</td>
      <td className={styles.numeric}>
        {item.issueNumber != null ? `#${item.issueNumber}` : '—'}
      </td>
      <td className={styles.titleCell}>{item.title}</td>
      <td className={styles.muted}>
        {item.protocol}
        {item.downloadClient ? ` · ${item.downloadClient}` : ''}
      </td>
      <td className={styles.muted}>{item.indexer ?? '—'}</td>
      <td className={styles.progressCell}>
        {failed ? (
          <span className={styles.muted}>—</span>
        ) : (
          <>
            <div
              className={styles.progressTrack}
              role="progressbar"
              aria-valuenow={item.progress}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`${item.title} progress`}
            >
              <div
                className={styles.progressFill}
                style={{ width: `${item.progress}%` }}
              />
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
          </>
        )}
      </td>
      <td className={styles.numeric}>
        {failed ? '—' : formatEta(item.estimatedCompletion)}
      </td>
      <td className={styles.actionsCell}>
        <span className={styles.actionsGroup}>
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
        </span>
      </td>
    </tr>
  );
}
