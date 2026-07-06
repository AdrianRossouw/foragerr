import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Toolbar } from '../../components/Toolbar';
import { PageControls } from '../../components/PageControls';
import { ReasonsPopover } from '../../components/ReasonsPopover';
import { useHistoryPage } from '../../api/hooks';
import { queryKeys } from '../../api/queryKeys';
import { HISTORY_EVENT_TYPES, type HistoryRecord } from '../../api/types';
import { formatDate } from '../../lib/format';
import styles from './HistoryScreen.module.css';

/**
 * Activity: History (FRG-UI-010) — the paged single-source feed of pipeline
 * events over GET /api/v1/history, newest first. Event types render as text
 * chips (no icon system), rows link to their series, and each row expands to
 * the event's canonical data payload with rejection reasons rendered VERBATIM
 * through the shared ReasonsPopover. Pagination is real server-side paging
 * (design decision 5); the WebSocketBridge invalidates ['history'] on queue
 * pushes (imports/failures write history rows), and the Refresh button covers
 * event writers that emit no push at all (e.g. manual file deletes).
 */

const EVENT_LABEL: Record<string, string> = {
  grabbed: 'Grabbed',
  imported: 'Imported',
  upgrade_replaced: 'Upgraded',
  import_blocked: 'Import Blocked',
  import_failed: 'Import Failed',
  download_failed: 'Download Failed',
  file_deleted: 'File Deleted',
  file_renamed: 'File Renamed',
  comicinfo_tag_failed: 'Tag Failed',
};

const EVENT_CHIP: Record<string, string> = {
  grabbed: styles.chipInfo,
  imported: styles.chipGood,
  upgrade_replaced: styles.chipGood,
  import_blocked: styles.chipWarn,
  import_failed: styles.chipDanger,
  download_failed: styles.chipDanger,
  file_deleted: styles.chipNeutral,
  file_renamed: styles.chipNeutral,
  comicinfo_tag_failed: styles.chipWarn,
};

function eventLabel(eventType: string): string {
  return EVENT_LABEL[eventType] ?? eventType;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === 'string');
}

/** One data-payload value, rendered read-only. Reasons get the shared popover. */
function DetailValue({ record, name, value }: {
  record: HistoryRecord;
  name: string;
  value: unknown;
}) {
  if (name === 'reasons' && isStringArray(value)) {
    return (
      <ReasonsPopover
        reasons={value}
        label={`Rejection reasons for ${record.sourceTitle ?? `event ${record.id}`}`}
        chipClassName={styles.reasonChip}
        chipContent={<>! {value.length === 1 ? '1 reason' : `${value.length} reasons`}</>}
        listTestId={`ft-history-reasons-${record.id}`}
      />
    );
  }
  if (value === null || value === undefined) return <>—</>;
  if (typeof value === 'string') return <>{value}</>;
  if (typeof value === 'number' || typeof value === 'boolean') {
    return <>{String(value)}</>;
  }
  if (isStringArray(value)) return <>{value.join(', ')}</>;
  return <>{JSON.stringify(value)}</>;
}

function DetailsRow({ record }: { record: HistoryRecord }) {
  const entries = Object.entries(record.data);
  return (
    <tr data-testid={`history-details-${record.id}`}>
      <td colSpan={6}>
        {entries.length === 0 ? (
          <span className={styles.muted}>No additional details.</span>
        ) : (
          <dl className={styles.detailsList}>
            {entries.map(([name, value]) => (
              <div key={name} style={{ display: 'contents' }}>
                <dt>{name}</dt>
                <dd>
                  <DetailValue record={record} name={name} value={value} />
                </dd>
              </div>
            ))}
          </dl>
        )}
      </td>
    </tr>
  );
}

function HistoryRow({ record, expanded, onToggle }: {
  record: HistoryRecord;
  expanded: boolean;
  onToggle: () => void;
}) {
  const chipClass = `${styles.chip} ${EVENT_CHIP[record.eventType] ?? styles.chipNeutral}`;
  return (
    <>
      <tr data-testid={`history-row-${record.id}`}>
        <td>
          <span className={chipClass}>{eventLabel(record.eventType)}</span>
        </td>
        <td>{record.sourceTitle ?? '—'}</td>
        <td>
          {record.series ? (
            <Link className={styles.seriesLink} to={`/series/${record.series.id}`}>
              {record.series.title}
            </Link>
          ) : (
            '—'
          )}
        </td>
        {/* Verbatim string issue number — never coerced. */}
        <td className={styles.numeric}>
          {record.issue?.issueNumber != null ? `#${record.issue.issueNumber}` : '—'}
        </td>
        <td className={styles.numeric}>{formatDate(record.date)}</td>
        <td className={styles.detailsCell}>
          <button
            type="button"
            className={styles.btn}
            aria-expanded={expanded}
            aria-label={`Toggle details for event ${record.id}`}
            onClick={onToggle}
          >
            {expanded ? 'Hide details' : 'Details'}
          </button>
        </td>
      </tr>
      {expanded && <DetailsRow record={record} />}
    </>
  );
}

export function HistoryScreen() {
  const [page, setPage] = useState(1);
  const [eventType, setEventType] = useState('');
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set());
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useHistoryPage(page, { eventType });

  const records = data?.records ?? [];

  const toggleExpanded = (id: number) => {
    const next = new Set(expanded);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpanded(next);
  };

  const changeFilter = (value: string) => {
    setEventType(value);
    setPage(1);
    setExpanded(new Set());
  };

  return (
    <>
      <Toolbar
        title="History"
        actions={
          <span className={styles.toolbarActions}>
            <select
              className={styles.filterSelect}
              aria-label="Filter by event type"
              value={eventType}
              onChange={(e) => changeFilter(e.target.value)}
            >
              <option value="">All events</option>
              {HISTORY_EVENT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {eventLabel(type)}
                </option>
              ))}
            </select>
            <button
              type="button"
              className={styles.btn}
              onClick={() =>
                void queryClient.invalidateQueries({
                  queryKey: queryKeys.history.all(),
                })
              }
            >
              Refresh
            </button>
          </span>
        }
      />
      <div>
        {isLoading && <p className={styles.state}>Loading history…</p>}
        {isError && <p className={styles.state}>Could not load history.</p>}
        {!isLoading && !isError && records.length === 0 && (
          <p className={styles.state}>No history events.</p>
        )}
        {records.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Event</th>
                <th>Source Title</th>
                <th>Series</th>
                <th>Issue</th>
                <th>Date</th>
                <th aria-label="Details" />
              </tr>
            </thead>
            <tbody>
              {records.map((record) => (
                <HistoryRow
                  key={record.id}
                  record={record}
                  expanded={expanded.has(record.id)}
                  onToggle={() => toggleExpanded(record.id)}
                />
              ))}
            </tbody>
          </table>
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
    </>
  );
}
