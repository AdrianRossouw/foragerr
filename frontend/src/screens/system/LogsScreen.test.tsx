import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor, within, act, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { makeLogRecord } from '../../test/mockData';
import { ApiRequestError } from '../../api/fetcher';
import { LOG_FOLLOW_INTERVAL_MS } from '../../api/hooks';
import type { ApiPage, LogLevel, LogRecordResource } from '../../api/types';
import { formatDateTime } from '../../lib/format';
import { LogsScreen } from './LogsScreen';

/**
 * FRG-UI-024 — System: Logs screen. Renders GET /api/v1/log (the buffered,
 * already-redacted log ring, newest first) as a dense table with a
 * minimum-level filter, a logger-prefix filter, and a Follow toggle. All data
 * rides the fake fetcher; no live backend.
 */

const SEVERITY: Record<LogLevel, number> = { DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3 };

function logEnvelope(records: LogRecordResource[]): ApiPage<LogRecordResource> {
  return {
    page: 1,
    pageSize: 100,
    sortKey: 'time',
    sortDirection: 'desc',
    totalRecords: records.length,
    records,
  };
}

/** Mixed-level, mixed-logger buffered records (matches the scenario text). */
const MIXED_RECORDS: LogRecordResource[] = [
  makeLogRecord({
    time: '2026-07-10T01:00:00Z',
    level: 'DEBUG',
    logger: 'foragerr.core',
    message: 'Loaded configuration',
  }),
  makeLogRecord({
    time: '2026-07-10T02:00:00Z',
    level: 'INFO',
    logger: 'foragerr.ddl',
    message: 'Started DDL fetch',
  }),
  makeLogRecord({
    time: '2026-07-10T03:00:00Z',
    level: 'WARNING',
    logger: 'foragerr.indexer',
    message: 'Indexer slow to respond',
  }),
  makeLogRecord({
    time: '2026-07-10T04:00:00Z',
    level: 'ERROR',
    logger: 'foragerr.ddl',
    message: 'DDL fetch failed: connection reset',
  }),
];

/** A fetcher that filters MIXED_RECORDS by the request's own level/logger params, the way the real backend does server-side. */
function mixedLevelFetcher() {
  return fakeFetcher((path) => {
    const url = new URL(path, 'http://localhost');
    const level = url.searchParams.get('level') as LogLevel | null;
    const loggerPrefix = url.searchParams.get('logger');
    let records = MIXED_RECORDS;
    if (level) records = records.filter((r) => SEVERITY[r.level] >= SEVERITY[level]);
    if (loggerPrefix) records = records.filter((r) => r.logger.startsWith(loggerPrefix));
    return logEnvelope(records);
  });
}

describe('FRG-UI-024: logs table renders with filters', () => {
  it('FRG-UI-024 — the table renders mixed-level buffered records, and applying a minimum level and a logger prefix requests and shows only the matching rows', async () => {
    const { spy, fetcher } = mixedLevelFetcher();
    const user = userEvent.setup();
    renderWithProviders(<LogsScreen />, { fetcher });

    await waitFor(() => expect(screen.getAllByTestId('log-row')).toHaveLength(4));

    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Minimum level' }),
      'ERROR',
    );
    await user.type(screen.getByRole('textbox', { name: 'Logger prefix' }), 'foragerr.ddl');

    await waitFor(() => expect(screen.getAllByTestId('log-row')).toHaveLength(1));
    const row = screen.getByTestId('log-row');
    expect(within(row).getByTestId('log-level-pill')).toHaveTextContent('ERROR');
    expect(within(row).getByText('foragerr.ddl')).toBeInTheDocument();
    expect(
      within(row).getByTitle('DDL fetch failed: connection reset'),
    ).toBeInTheDocument();
    expect(
      within(row).getByText(formatDateTime('2026-07-10T04:00:00Z')),
    ).toBeInTheDocument();

    // The request itself carries the applied filters (server-side filtering).
    expect(
      spy.mock.calls.some(
        ([p]) =>
          typeof p === 'string' &&
          p.includes('level=ERROR') &&
          p.includes('logger=foragerr.ddl'),
      ),
    ).toBe(true);
  });
});

describe('FRG-UI-024: Follow polls and stops', () => {
  it('FRG-UI-024 — with Follow on, the resource re-fetches on the polling interval and new records appear without a reload', async () => {
    let recordCount = 1;
    const { spy, fetcher } = fakeFetcher(() =>
      logEnvelope(
        Array.from({ length: recordCount }, (_, i) =>
          makeLogRecord({ time: `2026-07-10T0${i + 1}:00:00Z`, message: `event ${i}` }),
        ),
      ),
    );

    // Fake timers must be installed BEFORE mount: React Query registers its
    // refetchInterval timer against whichever setTimeout is global at mount
    // time (mirrors the HealthScreen precedent for FRG-UI-016).
    vi.useFakeTimers();
    try {
      renderWithProviders(<LogsScreen />, { fetcher });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getAllByTestId('log-row')).toHaveLength(1);
      const initialCalls = spy.mock.calls.length;

      recordCount = 2;
      // Advance past two poll intervals (HealthScreen/FRG-UI-016 precedent):
      // one interval is sometimes not enough for the fake-timer-driven fetch
      // AND its resulting React re-render to both land within the same
      // advance.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(LOG_FOLLOW_INTERVAL_MS * 2);
      });

      expect(spy.mock.calls.length).toBeGreaterThan(initialCalls);
      expect(screen.getAllByTestId('log-row')).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('FRG-UI-024 — turning Follow off stops polling, and leaving the screen (unmount) also stops it', async () => {
    const { spy, fetcher } = fakeFetcher(() => logEnvelope([makeLogRecord()]));

    vi.useFakeTimers();
    try {
      const { unmount } = renderWithProviders(<LogsScreen />, { fetcher });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      const callsWhileFollowing = spy.mock.calls.length;

      // Follow starts ON by default — turn it off.
      fireEvent.click(screen.getByTestId('log-follow-toggle'));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(LOG_FOLLOW_INTERVAL_MS * 3);
      });
      expect(spy.mock.calls.length).toBe(callsWhileFollowing);

      // Turn Follow back on to prove polling resumes...
      fireEvent.click(screen.getByTestId('log-follow-toggle'));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(LOG_FOLLOW_INTERVAL_MS);
      });
      expect(spy.mock.calls.length).toBeGreaterThan(callsWhileFollowing);
      const callsBeforeUnmount = spy.mock.calls.length;

      // ...then unmount and prove polling stops for good, not just paused.
      unmount();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(LOG_FOLLOW_INTERVAL_MS * 3);
      });
      expect(spy.mock.calls.length).toBe(callsBeforeUnmount);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('FRG-UI-024: empty and error states are honest', () => {
  it('FRG-UI-024 — an empty log buffer renders an honest empty state, never a silent blank table', async () => {
    const { fetcher } = fakeFetcher(() => logEnvelope([]));
    renderWithProviders(<LogsScreen />, { fetcher });

    await waitFor(() =>
      expect(screen.getByText('No log records buffered yet…')).toBeInTheDocument(),
    );
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('FRG-UI-024 — a failed log request renders an honest error state, never a silent blank table', async () => {
    const { fetcher } = fakeFetcher(() => {
      throw new ApiRequestError(500, null, '/api/v1/log');
    });
    renderWithProviders(<LogsScreen />, { fetcher });

    await waitFor(() =>
      expect(screen.getByText('Could not load log records.')).toBeInTheDocument(),
    );
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});
