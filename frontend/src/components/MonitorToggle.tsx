import { BookmarkIcon } from './icons';
import styles from './MonitorToggle.module.css';

/**
 * Monitored bookmark toggle (Sonarr's P-primitive): filled accent bookmark
 * when monitored, hollow when not. Accessible as a pressed toggle button.
 */
export function MonitorToggle({
  monitored,
  onToggle,
  label,
  size = 18,
  disabled = false,
}: {
  monitored: boolean;
  onToggle: () => void;
  /** Accessible subject, e.g. "series" or `issue 1.5`. */
  label: string;
  size?: number;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className={monitored ? `${styles.toggle} ${styles.monitored}` : styles.toggle}
      aria-pressed={monitored}
      aria-label={`${monitored ? 'Unmonitor' : 'Monitor'} ${label}`}
      title={monitored ? 'Monitored' : 'Unmonitored'}
      onClick={onToggle}
      disabled={disabled}
    >
      <BookmarkIcon filled={monitored} size={size} />
    </button>
  );
}
