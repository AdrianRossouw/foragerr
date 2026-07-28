import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Toolbar } from '../../components/Toolbar';
import { PageControls } from '../../components/PageControls';
import { PersonIcon, SearchIcon } from '../../components/icons';
import { InteractiveSearchOverlay } from '../search/InteractiveSearchOverlay';
import {
  useRunCommand,
  useSystemTasks,
  useWantedPage,
  useWatchedCommand,
} from '../../api/hooks';
import { queryKeys } from '../../api/queryKeys';
import type { WantedIssueRecord } from '../../api/types';
import { formatDate, formatDateTime } from '../../lib/format';
import styles from './WantedScreen.module.css';

/**
 * Wanted: Missing (FRG-UI-011) — the derived missing list (monitored,
 * published, no file) over GET /api/v1/wanted/missing. Per-row automatic
 * search enqueues the existing issue-search command; interactive search opens
 * the existing overlay scoped to the issue; Search All enqueues ONE
 * backlog-search command whose status stays visible until terminal via the
 * shared useWatchedCommand machinery. Plain missing only — the cutoff-unmet
 * half is removed with the M2 reshape.
 */

/** The release date column tolerates whichever date field the backend serves. */
function releaseDate(record: WantedIssueRecord): string | null {
  return record.store_date ?? record.cover_date ?? null;
}

const BACKLOG_SEARCH_TASK = 'backlog-search';

/**
 * "Next automatic search at …" (FRG-SCHED-012) — a READ of the scheduler's own
 * next-run data (GET /api/v1/system/task, the Tasks screen's source), never a
 * second scheduler and never a second endpoint. Renders nothing when the task
 * or its next-run is absent: no invented promise about when the machine looks.
 */
function NextAutomaticSearch() {
  const { data } = useSystemTasks();
  // Defensive: only ever index into a real array from this shared query.
  const tasks = Array.isArray(data) ? data : [];
  const nextRun = tasks.find((t) => t.name === BACKLOG_SEARCH_TASK)?.next_run;
  if (!nextRun) return null;

  return (
    <p className={styles.nextSearch} data-testid="next-automatic-search">
      Next automatic search at {formatDateTime(nextRun)}
    </p>
  );
}

export function WantedScreen() {
  const [page, setPage] = useState(1);
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useWantedPage(page, setPage);
  const runCommand = useRunCommand();

  // One shared command watcher: Search All and the per-row automatic searches
  // all surface their status through the same toolbar chip (SeriesDetail's
  // pattern). A completed search may have grabbed releases — the wanted list
  // and queue are stale then; a failed command completed nothing.
  const [commandLabel, setCommandLabel] = useState<string | null>(null);
  const command = useWatchedCommand((status) => {
    if (status === 'completed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.wanted.all() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.queue.all() });
    }
  });

  const [searchIssue, setSearchIssue] = useState<WantedIssueRecord | null>(null);

  const records = data?.records ?? [];

  const dispatch = (label: string, name: string, payload?: Record<string, unknown>) => {
    runCommand.mutate(
      { name, payload },
      {
        onSuccess: (record) => {
          setCommandLabel(label);
          command.start(record.id);
        },
      },
    );
  };

  return (
    <>
      <Toolbar
        title="Wanted — Missing"
        actions={
          <span className={styles.toolbarActions}>
            {commandLabel && command.status && (
              <span className={styles.commandChip} data-testid="command-status">
                {commandLabel}: {command.status}
              </span>
            )}
            <button
              type="button"
              className={styles.btn}
              disabled={command.running || runCommand.isPending}
              onClick={() => dispatch('Search All', 'backlog-search')}
            >
              Search All
            </button>
          </span>
        }
      />
      <div>
        <NextAutomaticSearch />
        {isLoading && <p className={styles.state}>Loading wanted issues…</p>}
        {isError && <p className={styles.state}>Could not load wanted issues.</p>}
        {!isLoading && !isError && records.length === 0 && (
          <p className={styles.state}>
            Nothing is missing — every monitored issue has a file.
          </p>
        )}
        {records.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Series</th>
                <th>Issue</th>
                <th>Title</th>
                <th>Release Date</th>
                <th className={styles.actionsCell}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record) => (
                <tr key={record.id} data-testid={`wanted-row-${record.id}`}>
                  <td>
                    {record.series ? (
                      <Link
                        className={styles.seriesLink}
                        to={`/series/${record.series.id}`}
                      >
                        {record.series.title}
                      </Link>
                    ) : (
                      '—'
                    )}
                  </td>
                  {/* Verbatim string issue number — never coerced. */}
                  <td className={styles.numeric}>
                    {record.issue_number != null ? `#${record.issue_number}` : '—'}
                  </td>
                  <td>{record.title ?? '—'}</td>
                  <td className={styles.numeric}>{formatDate(releaseDate(record))}</td>
                  <td className={styles.actionsCell}>
                    <button
                      type="button"
                      className={styles.iconButton}
                      aria-label={`Automatic search for issue ${record.issue_number ?? record.id}`}
                      // One shared watcher backs every automatic search: starting
                      // a per-row search mid-run would hijack Search All's
                      // completion (its invalidation + chip). Disable automatic
                      // searches while one runs; interactive search stays open.
                      title={
                        command.running
                          ? 'A search is already running'
                          : 'Automatic search'
                      }
                      disabled={command.running}
                      onClick={() =>
                        dispatch(
                          `Search #${record.issue_number ?? record.id}`,
                          'issue-search',
                          { series_id: record.series_id, issue_id: record.id },
                        )
                      }
                    >
                      <SearchIcon size={14} />
                    </button>
                    <button
                      type="button"
                      className={styles.iconButton}
                      aria-label={`Interactive search for issue ${record.issue_number ?? record.id}`}
                      title="Interactive search"
                      onClick={() => setSearchIssue(record)}
                    >
                      <PersonIcon size={14} />
                    </button>
                  </td>
                </tr>
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

      {/* The existing per-issue overlay (FRG-UI-007), scoped to the row. */}
      {searchIssue && (
        <div
          data-testid="interactive-search-overlay"
          data-issue-id={searchIssue.id}
        >
          <InteractiveSearchOverlay
            issueId={searchIssue.id}
            contextTitle={`${searchIssue.series?.title ?? ''} #${searchIssue.issue_number ?? searchIssue.id}`}
            onClose={() => setSearchIssue(null)}
          />
        </div>
      )}
    </>
  );
}
