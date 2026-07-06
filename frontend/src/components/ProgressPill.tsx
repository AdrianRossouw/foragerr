import styles from './ProgressPill.module.css';

/**
 * The Sonarr "have/total" progress pill: a compact count chip whose fill
 * ratio mirrors completion. Numbers stay visible (colorblind-safe — the
 * counts, not just the color, carry the missing-issues state; deliberate
 * divergence from Sonarr's corner-triangle affordance).
 */
export function ProgressPill({
  have,
  total,
  monitored = true,
}: {
  have: number;
  total: number;
  monitored?: boolean;
}) {
  const complete = total > 0 && have >= total;
  const ratio = total > 0 ? Math.min(have / total, 1) : 0;
  const variant = complete
    ? styles.complete
    : monitored
      ? styles.missing
      : styles.unmonitored;
  return (
    <span
      className={`${styles.pill} ${variant}`}
      role="status"
      aria-label={`${have} of ${total} issues on disk`}
    >
      <span className={styles.fill} style={{ width: `${ratio * 100}%` }} aria-hidden />
      <span className={styles.count}>
        {have}/{total}
      </span>
    </span>
  );
}
