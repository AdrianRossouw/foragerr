import type { SeriesResource } from '../api/types';
import styles from './BookTypeBadge.module.css';

/**
 * Book-type badge (FRG-UI-022): a subtle Sonarr-shaped chip marking a series'
 * collected-edition type (FRG-SER-018) so a trade/GN/hardcover reads distinctly
 * from an ordinary single-issues run. Display-only — it renders NOTHING for a
 * null book-type (a single-issues run carries no badge) and never affects
 * monitoring, actions, or the wanted machinery.
 */

type BookType = NonNullable<SeriesResource['booktype']>;

/** Short chip label + a spelled-out title/aria description per book-type. */
const LABELS: Record<BookType, { short: string; full: string }> = {
  tpb: { short: 'TPB', full: 'Trade paperback' },
  gn: { short: 'GN', full: 'Graphic novel' },
  hc: { short: 'HC', full: 'Hardcover' },
  one_shot: { short: 'ONE-SHOT', full: 'One-shot' },
};

export function BookTypeBadge({
  booktype,
}: {
  booktype: SeriesResource['booktype'];
}) {
  if (booktype === null) return null;
  const { short, full } = LABELS[booktype];
  return (
    <span
      className={styles.badge}
      data-testid="booktype-badge"
      data-booktype={booktype}
      title={`Collected edition: ${full}`}
      aria-label={`Collected edition: ${full}`}
    >
      {short}
    </span>
  );
}
