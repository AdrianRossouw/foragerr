import { Popover } from '../../components/Popover';
import type { QueueItem, QueueItemStatus } from '../../api/types';
import styles from './QueueScreen.module.css';

const STATUS_LABEL: Record<QueueItemStatus, string> = {
  downloading: 'Downloading',
  import_pending: 'Waiting to import',
  import_blocked: 'Import blocked',
  importing: 'Importing',
  imported: 'Imported',
  failed_pending: 'Failing',
  failed: 'Failed',
  ignored: 'Ignored',
};

const STATUS_CHIP_CLASS: Record<QueueItemStatus, string> = {
  downloading: styles.chipDownloading,
  import_pending: styles.chipPending,
  import_blocked: styles.chipBlocked,
  importing: styles.chipImporting,
  imported: styles.chipNeutral,
  failed_pending: styles.chipFailed,
  failed: styles.chipFailed,
  ignored: styles.chipNeutral,
};

/** States whose chip always expands to a reason popover (FRG-UI-006). */
const REASON_STATES: ReadonlySet<QueueItemStatus> = new Set([
  'import_pending',
  'import_blocked',
]);

const REASON_FALLBACK: Partial<Record<QueueItemStatus, string>> = {
  import_pending:
    'Download complete — waiting for the import pipeline to pick it up.',
  import_blocked: 'Import blocked — manual intervention required.',
};

/**
 * Queue status chip. For import_pending / import_blocked rows (and any row the
 * backend flagged with status messages) the chip is a popover trigger revealing
 * the backend's reason text verbatim.
 */
export function QueueStatusChip({ item }: { item: QueueItem }) {
  const label = STATUS_LABEL[item.status];
  const chipClass = `${styles.chip} ${STATUS_CHIP_CLASS[item.status]}`;
  const expandable = REASON_STATES.has(item.status) || item.statusMessages.length > 0;

  if (!expandable) {
    return <span className={chipClass}>{label}</span>;
  }

  return (
    <Popover trigger={<span className={chipClass}>{label}</span>} label={label}>
      {item.statusMessages.length > 0 ? (
        <ul className={styles.reasonList}>
          {item.statusMessages.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      ) : (
        <p className={styles.reasonFallback}>{REASON_FALLBACK[item.status] ?? label}</p>
      )}
    </Popover>
  );
}
