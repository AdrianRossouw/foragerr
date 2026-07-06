import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useCommandStatus } from '../../../api/hooks';
import { queryKeys } from '../../../api/queryKeys';
import { useExecuteRename, useRenamePreview } from './namingHooks';
import styles from './MediaManagement.module.css';

/*
 * Per-series rename preview (FRG-UI-012 / FRG-PP-012). A pure server-side
 * preview (GET /rename) lists the existing -> new path diffs; NOTHING touches
 * disk until the operator explicitly confirms, which POSTs /rename to enqueue
 * the rename-series command. The command's progress surfaces through the shared
 * command machinery (useCommandStatus), and on completion the preview + the
 * affected series/issues caches are invalidated.
 */

const LIVE_STATUSES = new Set(['queued', 'started']);

/** Last path segment, for a compact old -> new basename diff. */
function basename(path: string): string {
  const parts = path.split('/');
  return parts[parts.length - 1] || path;
}

interface RenamePreviewPanelProps {
  seriesId: number;
  seriesTitle: string;
  onClose: () => void;
}

export function RenamePreviewPanel({
  seriesId,
  seriesTitle,
  onClose,
}: RenamePreviewPanelProps) {
  const preview = useRenamePreview(seriesId);
  const execute = useExecuteRename();
  const queryClient = useQueryClient();
  const [commandId, setCommandId] = useState<number | null>(null);

  const commandQuery = useCommandStatus(commandId);
  const status = commandQuery.data?.status ?? (commandId !== null ? 'queued' : null);
  const finished = status !== null && !LIVE_STATUSES.has(status) ? status : null;

  useEffect(() => {
    if (finished) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.rename.forSeries(seriesId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.series.detail(seriesId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.issues.forSeries(seriesId) });
    }
  }, [finished, queryClient, seriesId]);

  const rows = preview.data ?? [];
  const confirmed = commandId !== null;

  const onConfirm = () => {
    execute.mutate(seriesId, { onSuccess: (cmd) => setCommandId(cmd.id) });
  };

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div
        className={styles.modal}
        role="dialog"
        aria-modal="true"
        aria-label={`Rename preview — ${seriesTitle}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>Rename — {seriesTitle}</span>
          <button
            type="button"
            className={styles.iconButton}
            aria-label="Close"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <div className={styles.modalBody}>
          {preview.isLoading && <p className={styles.stateText}>Computing preview…</p>}
          {preview.isError && (
            <p className={styles.stateText}>Could not compute the rename preview.</p>
          )}
          {preview.isSuccess && rows.length === 0 && (
            <p className={styles.stateText} data-testid="rename-no-changes">
              All files already match the current template — nothing to rename.
            </p>
          )}
          {rows.length > 0 && (
            <table className={styles.renameTable} data-testid="rename-preview-table">
              <thead>
                <tr>
                  <th>Current name</th>
                  <th aria-hidden>→</th>
                  <th>New name</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.issueFileId} data-testid={`rename-row-${row.issueFileId}`}>
                    <td className={styles.renameOld}>{basename(row.existingPath)}</td>
                    <td aria-hidden className={styles.renameArrow}>→</td>
                    <td className={styles.renameNew}>{basename(row.newPath)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {status && (
            <div className={styles.commandChip} data-testid="rename-command-status">
              Rename: {status}
            </div>
          )}
          {execute.isError && (
            <div className={styles.fieldError} role="alert">
              {execute.error.message}
            </div>
          )}
        </div>
        <div className={styles.modalFooter}>
          <span className={styles.footerSpacer} />
          <button type="button" className={styles.button} onClick={onClose}>
            {finished ? 'Close' : 'Cancel'}
          </button>
          <button
            type="button"
            className={`${styles.button} ${styles.buttonPrimary}`}
            disabled={rows.length === 0 || confirmed || execute.isPending}
            onClick={onConfirm}
            data-testid="rename-confirm"
          >
            {confirmed ? 'Renaming…' : `Rename ${rows.length} file${rows.length === 1 ? '' : 's'}`}
          </button>
        </div>
      </div>
    </div>
  );
}
