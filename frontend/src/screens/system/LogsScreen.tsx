import { useState } from 'react';
import { Toolbar } from '../../components/Toolbar';
import { PageControls } from '../../components/PageControls';
import { useLogPage } from '../../api/hooks';
import { LOG_LEVELS, type LogLevel } from '../../api/types';
import { formatDateTime } from '../../lib/format';
import systemStyles from './System.module.css';
import styles from './LogsScreen.module.css';

/**
 * System — Logs (FRG-UI-024). Renders GET /api/v1/log: the buffered,
 * already-redacted log ring as a dense table (time, level pill, logger,
 * message), with a minimum-level filter, a logger-prefix filter, and a
 * Follow toggle. Follow on polls page 1 on a short interval and keeps the
 * newest records in view (design decision 2 — polling, not a WS push);
 * Follow off stops polling and hands paging to the operator via the shared
 * PageControls. Never a silent blank: loading/error/empty all render an
 * explicit message (UAT negative-path rule).
 */

const LEVEL_LABEL: Record<LogLevel, string> = {
  DEBUG: 'Debug',
  INFO: 'Info',
  WARNING: 'Warning',
  ERROR: 'Error',
};

// ERROR danger, WARNING warn, INFO neutral, DEBUG muted (FRG-UI-024).
const LEVEL_PILL_CLASS: Record<LogLevel, string> = {
  ERROR: styles.pillDanger,
  WARNING: styles.pillWarn,
  INFO: styles.pillNeutral,
  DEBUG: styles.pillMuted,
};

export function LogsScreen() {
  const [page, setPage] = useState(1);
  // '' = the "All levels" option; any other value is a valid LogLevel.
  const [level, setLevel] = useState<LogLevel | ''>('');
  const [logger, setLogger] = useState('');
  const [follow, setFollow] = useState(true);

  const { data, isLoading, isError } = useLogPage({ page, level, logger, follow });
  const records = data?.records ?? [];

  const changeLevel = (value: LogLevel | '') => {
    setLevel(value);
    setPage(1);
  };

  const changeLogger = (value: string) => {
    setLogger(value);
    setPage(1);
  };

  return (
    <>
      <Toolbar
        title="System — Logs"
        actions={
          <span className={styles.toolbarActions}>
            <select
              className={styles.filterSelect}
              aria-label="Minimum level"
              value={level}
              onChange={(e) => changeLevel(e.target.value as LogLevel | '')}
            >
              <option value="">All levels</option>
              {LOG_LEVELS.map((l) => (
                <option key={l} value={l}>
                  {LEVEL_LABEL[l]}
                </option>
              ))}
            </select>
            <input
              type="text"
              className={styles.filterInput}
              aria-label="Logger prefix"
              placeholder="Logger prefix…"
              value={logger}
              onChange={(e) => changeLogger(e.target.value)}
            />
            <span className={styles.followRow}>
              <span className={styles.followLabel}>Follow</span>
              <button
                type="button"
                role="switch"
                aria-checked={follow}
                aria-label="Follow"
                data-testid="log-follow-toggle"
                className={styles.switch}
                data-on={follow}
                onClick={() => {
                  setFollow((f) => !f);
                  setPage(1);
                }}
              >
                <span className={styles.switchKnob} aria-hidden />
              </button>
            </span>
          </span>
        }
      />
      <div className={systemStyles.page}>
        {isLoading && <p className={systemStyles.state}>Loading log records…</p>}
        {isError && <p className={systemStyles.state}>Could not load log records.</p>}
        {!isLoading && !isError && records.length === 0 && (
          <p className={systemStyles.state}>No log records buffered yet…</p>
        )}
        {records.length > 0 && (
          <table className={systemStyles.table}>
            <thead>
              <tr>
                <th>Time</th>
                <th>Level</th>
                <th>Logger</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record, index) => (
                <tr key={`${record.time}-${index}`} data-testid="log-row">
                  <td className={systemStyles.muted}>{formatDateTime(record.time)}</td>
                  <td>
                    <span
                      className={`${styles.pill} ${LEVEL_PILL_CLASS[record.level]}`}
                      data-testid="log-level-pill"
                    >
                      {record.level}
                    </span>
                  </td>
                  <td className={systemStyles.muted}>{record.logger}</td>
                  <td className={styles.message} title={record.message}>
                    {record.message}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {!follow && data && (
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
