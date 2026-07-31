import { useState } from 'react';
import { Modal } from '../../components/Modal';
import { useRemoveQueueItems, type QueueRemoveResult } from '../../api/hooks';
import type { QueueItem } from '../../api/types';
import styles from './QueueScreen.module.css';

export interface RemoveQueueDialogProps {
  /** The rows to remove — one from a row action, many from a selection. */
  items: QueueItem[];
  onClose: () => void;
  /** Handed the per-row outcome so the screen can report what did not remove. */
  onRemoved?: (result: QueueRemoveResult) => void;
}

/** Series + issue when the row is mapped, else the raw release name. */
export function queueItemName(item: QueueItem): string {
  return item.seriesTitle
    ? `${item.seriesTitle}${item.issueNumber != null ? ` #${item.issueNumber}` : ''}`
    : item.title;
}

/**
 * Sonarr-style remove-queue-item dialog (FRG-UI-006): confirm removal with
 * independent delete-data and blocklist options. One item or fifty, the options
 * are the same and are always an explicit choice — a bulk clear never carries a
 * blocklist default the operator did not tick.
 */
export function RemoveQueueDialog({
  items,
  onClose,
  onRemoved,
}: RemoveQueueDialogProps) {
  const [deleteData, setDeleteData] = useState(false);
  const [blocklist, setBlocklist] = useState(false);
  const remove = useRemoveQueueItems();

  const single = items.length === 1 ? items[0] : null;
  const displayName = single ? queueItemName(single) : `${items.length} queue items`;

  return (
    <Modal
      title={`Remove — ${displayName}`}
      label={`Remove ${displayName} from queue`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className={styles.btn} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.btnDanger}
            disabled={remove.isPending || items.length === 0}
            onClick={() =>
              remove.mutate(
                { ids: items.map((item) => item.id), deleteData, blocklist },
                {
                  onSuccess: (result) => {
                    onRemoved?.(result);
                    onClose();
                  },
                },
              )
            }
          >
            {remove.isPending ? 'Removing…' : 'Remove'}
          </button>
        </>
      }
    >
      <p className={styles.dialogIntro}>
        Remove <strong>{displayName}</strong> from the queue?
      </p>
      {!single && (
        <ul className={styles.dialogTargets}>
          {items.map((item) => (
            <li key={item.id}>{queueItemName(item)}</li>
          ))}
        </ul>
      )}
      <label className={styles.dialogOption}>
        <input
          type="checkbox"
          checked={deleteData}
          onChange={(e) => setDeleteData(e.target.checked)}
        />
        <span>
          Remove from download client and delete data
          <span className={styles.dialogOptionHelp}>
            Also deletes the downloaded files from the client.
          </span>
        </span>
      </label>
      <label className={styles.dialogOption}>
        <input
          type="checkbox"
          checked={blocklist}
          onChange={(e) => setBlocklist(e.target.checked)}
        />
        <span>
          Blocklist release
          <span className={styles.dialogOptionHelp}>
            Prevents this release from being grabbed again.
          </span>
        </span>
      </label>
      {remove.isError && (
        <p role="alert" className={styles.reasonFallback}>
          Remove failed: {remove.error.message}
        </p>
      )}
    </Modal>
  );
}
