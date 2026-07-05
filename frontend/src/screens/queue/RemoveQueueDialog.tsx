import { useState } from 'react';
import { Modal } from '../../components/Modal';
import { useRemoveQueueItem } from '../../api/hooks';
import type { QueueItem } from '../../api/types';
import styles from './QueueScreen.module.css';

export interface RemoveQueueDialogProps {
  item: QueueItem;
  onClose: () => void;
}

/**
 * Sonarr-style remove-queue-item dialog (FRG-UI-006): confirm removal with
 * independent delete-data and blocklist options, mapping straight onto
 * `DELETE /api/v1/queue/{id}?deleteData=&blocklist=`.
 */
export function RemoveQueueDialog({ item, onClose }: RemoveQueueDialogProps) {
  const [deleteData, setDeleteData] = useState(false);
  const [blocklist, setBlocklist] = useState(false);
  const remove = useRemoveQueueItem();

  const displayName = item.seriesTitle
    ? `${item.seriesTitle}${item.issueNumber ? ` #${item.issueNumber}` : ''}`
    : item.title;

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
            disabled={remove.isPending}
            onClick={() =>
              remove.mutate(
                { id: item.id, deleteData, blocklist },
                { onSuccess: onClose },
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
