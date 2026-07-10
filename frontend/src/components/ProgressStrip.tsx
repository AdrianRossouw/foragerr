import styles from './ProgressStrip.module.css';

/**
 * Shared owned/total progress strip (FRG-UI-003, design decision 2). One
 * primitive for the whole library: a track whose color reflects completeness
 * (complete = green-tinted `--color-progress-complete`, incomplete =
 * red-tinted `--color-progress-incomplete`) and an accent-green fill
 * sized to the owned ratio. The count and/or percent read on top.
 *
 * Variants size it per context — `strip` (poster-card footer bar), `bar`
 * (overview row, taller), `mini` (dense table cell). All draw the same
 * track/fill semantics so a card, a row and a table cell never disagree about
 * what "complete" looks like.
 */
export type ProgressStripVariant = 'strip' | 'bar' | 'mini';

export function ProgressStrip({
  have,
  total,
  monitored = true,
  showCount = true,
  showPercent = false,
  variant = 'strip',
  className,
}: {
  have: number;
  total: number;
  monitored?: boolean;
  showCount?: boolean;
  showPercent?: boolean;
  variant?: ProgressStripVariant;
  className?: string;
}) {
  const complete = total > 0 && have >= total;
  const ratio = total > 0 ? Math.min(have / total, 1) : 0;
  const pct = Math.round(ratio * 100);
  return (
    <span
      className={`${styles.root} ${styles[variant]}${className ? ` ${className}` : ''}`}
      data-complete={complete}
      data-monitored={monitored}
      role="status"
      aria-label={`${have} of ${total} issues on disk`}
    >
      <span className={styles.fill} style={{ width: `${ratio * 100}%` }} aria-hidden />
      {showCount && (
        <span className={styles.count}>
          {have} / {total}
        </span>
      )}
      {showPercent && <span className={styles.pct}>{pct}%</span>}
    </span>
  );
}
