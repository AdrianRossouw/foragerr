import { useNavigate } from 'react-router-dom';
import { Chip, type ChipTone } from '../../components/Chip';
import { BookOpenIcon, WrenchIcon } from '../../components/icons';
import { FORMAT_CHIP } from '../../theme/palettes';
import { formatDate } from '../../lib/format';
import type {
  BookType,
  CollectionRange,
  CollectionRecord,
  IssueResource,
  SeriesResource,
} from '../../api/types';
import styles from './SeriesDetail.module.css';

/** Short book-type label for the format chip / spine block. */
const BOOKTYPE_SHORT: Record<BookType, string> = {
  tpb: 'TPB',
  gn: 'GN',
  hc: 'HC',
  one_shot: 'ONE-SHOT',
};

/** Coverage → pill tone/label (FRG-UI-026): collected/partial/none. */
const COVERAGE: Record<CollectionRecord['coverage'], { tone: ChipTone; label: string }> = {
  collected: { tone: 'success', label: 'Collected' },
  partial: { tone: 'warning', label: 'Partial' },
  none: { tone: 'neutral', label: 'Not collected' },
};

/** Format-chip colors keyed by book-type, tokens-var neutral fallback. */
function formatChipStyle(booktype: BookType) {
  const fc = FORMAT_CHIP[booktype];
  return fc
    ? { background: fc.bg, color: fc.text }
    : { background: 'var(--surface-menu)', color: 'var(--text-secondary)' };
}

/** The trailing "Collects … · N issues · owned M" summary line. */
function collectsLine(record: CollectionRecord): string {
  const labels = record.ranges.map((r) => r.label).join(', ') || '—';
  return `Collects ${labels} · ${record.issues_in_ranges} issues · owned ${record.owned_in_ranges}`;
}

/** The tinted spine block + format chip that opens every collection row. */
function CollectionSpine({ booktype }: { booktype: BookType }) {
  return (
    <span className={styles.spine} style={formatChipStyle(booktype)} aria-hidden>
      {BOOKTYPE_SHORT[booktype]}
    </span>
  );
}

/**
 * Callback opening the containment dialog anchored to one trade issue
 * (FRG-UI-026). `defaultTargetSeriesId` pre-selects the collected series when
 * known (the single-issues run editing a trade that collects it).
 */
export type OpenContainment = (args: {
  anchorTradeIssueId: number;
  anchorTradeSeriesId: number;
  defaultTargetSeriesId: number | null;
  hasExisting: boolean;
  /** The trade issue's already-declared ranges (with resolved endpoint ids),
   * for the dialog to pre-fill in edit mode; empty when declaring fresh. */
  existingRanges: CollectionRange[];
}) => void;

/**
 * Collections tab (FRG-UI-026). Two shapes behind one endpoint:
 *
 *  - a collected edition (booktype set) lists ITS OWN issues so the operator
 *    can declare what each collects ("Declare contents");
 *  - a single-issues run lists the trades that collect it (read-only rows with
 *    Open + Edit).
 *
 * Display + declaration only — no acquisition action (FRG-SER-019).
 */
export function CollectionsTab({
  series,
  seriesId,
  collections,
  ownIssues,
  onOpenContainment,
}: {
  series: SeriesResource;
  seriesId: number;
  collections: CollectionRecord[];
  /** This series' own issues (the declare rows for a collected edition). */
  ownIssues: IssueResource[];
  onOpenContainment: OpenContainment;
}) {
  const navigate = useNavigate();
  const isTrade = series.booktype !== null;
  const recordByTradeIssue = new Map(collections.map((r) => [r.trade_issue_id, r]));

  // --- Collected edition: declare contents of each of its own issues. -------
  if (isTrade) {
    const booktype = series.booktype as BookType;
    if (ownIssues.length === 0) {
      return (
        <div className={styles.collectionsEmpty} data-testid="collections-empty">
          <BookOpenIcon size={22} />
          <p>This collection has no issues to declare contents for yet.</p>
        </div>
      );
    }
    return (
      <div className={styles.collectionsList}>
        {ownIssues.map((issue) => {
          const record = recordByTradeIssue.get(issue.id);
          const coverage = record ? COVERAGE[record.coverage] : null;
          return (
            <div className={styles.collectionRow} key={issue.id}>
              <CollectionSpine booktype={booktype} />
              <div className={styles.collectionMain}>
                <div className={styles.collectionTitleRow}>
                  <span className={styles.collectionTitle}>
                    {issue.title ?? `Volume ${issue.issue_number ?? issue.id}`}
                  </span>
                  <span className={styles.formatChip} style={formatChipStyle(booktype)}>
                    {BOOKTYPE_SHORT[booktype]}
                  </span>
                </div>
                <div className={styles.collectionMeta}>
                  {record ? collectsLine(record) : 'No contents declared'}
                </div>
              </div>
              {coverage && (
                <Chip tone={coverage.tone} testId={`coverage-${issue.id}`}>
                  {coverage.label}
                </Chip>
              )}
              <button
                type="button"
                className={styles.rowActionButton}
                aria-label={`Declare contents for ${issue.title ?? `issue ${issue.issue_number ?? issue.id}`}`}
                onClick={() =>
                  onOpenContainment({
                    anchorTradeIssueId: issue.id,
                    anchorTradeSeriesId: seriesId,
                    defaultTargetSeriesId: null,
                    hasExisting: record !== undefined,
                    existingRanges: record?.ranges ?? [],
                  })
                }
              >
                <WrenchIcon size={12} />
                {record ? 'Edit contents' : 'Declare contents'}
              </button>
            </div>
          );
        })}
      </div>
    );
  }

  // --- Single-issues run: the trades that collect it (read-only + Edit). ----
  if (collections.length === 0) {
    return (
      <div className={styles.collectionsEmpty} data-testid="collections-empty">
        <BookOpenIcon size={22} />
        <p>
          No collections yet. They appear here once a trade or collected edition
          declares that it collects these issues.
        </p>
      </div>
    );
  }
  return (
    <div className={styles.collectionsList}>
      {collections.map((record) => {
        const coverage = COVERAGE[record.coverage];
        return (
          <div className={styles.collectionRow} key={record.trade_issue_id}>
            <CollectionSpine booktype={record.booktype} />
            <div className={styles.collectionMain}>
              <div className={styles.collectionTitleRow}>
                <span className={styles.collectionTitle}>
                  {record.trade_series_title}
                </span>
                <span
                  className={styles.formatChip}
                  style={formatChipStyle(record.booktype)}
                >
                  {BOOKTYPE_SHORT[record.booktype]}
                </span>
              </div>
              <div className={styles.collectionMeta}>{collectsLine(record)}</div>
            </div>
            <span className={styles.collectionDate}>
              {formatDate(record.release_date)}
            </span>
            <Chip tone={coverage.tone} testId={`coverage-${record.trade_issue_id}`}>
              {coverage.label}
            </Chip>
            <button
              type="button"
              className={styles.rowActionButton}
              aria-label={`Open ${record.trade_series_title}`}
              onClick={() => navigate(`/series/${record.trade_series_id}`)}
            >
              <BookOpenIcon size={12} />
              Open
            </button>
            <button
              type="button"
              className={styles.rowActionButton}
              aria-label={`Edit containment for ${record.trade_series_title}`}
              onClick={() =>
                onOpenContainment({
                  anchorTradeIssueId: record.trade_issue_id,
                  anchorTradeSeriesId: record.trade_series_id,
                  defaultTargetSeriesId: seriesId,
                  hasExisting: true,
                  existingRanges: record.ranges,
                })
              }
            >
              <WrenchIcon size={12} />
              Edit
            </button>
          </div>
        );
      })}
    </div>
  );
}
