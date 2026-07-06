import { describe, it, expect } from 'vitest';
import { screen, waitFor, act, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { makeHistoryRecord, pageOf } from '../../test/mockData';
import { makeFakeSocketFactory } from '../../test/fakeSocket';
import { WebSocketBridge } from '../../ws/WebSocketBridge';
import { HistoryScreen } from './HistoryScreen';

/**
 * FRG-UI-010 — Activity: history screen. Paged pipeline events over
 * GET /api/v1/history: event-type chips, series/issue links, expandable
 * verbatim details, an event-type filter, REAL server-side pagination, and
 * WS-driven invalidation (imports ride the queue push).
 */

/** One grab→import cycle sharing a downloadId, newest (imported) first. */
const cycleRecords = [
  makeHistoryRecord({
    id: 2,
    eventType: 'imported',
    downloadId: 'SABnzbd_nzo_cycle',
    date: '2026-07-05T13:00:00Z',
  }),
  makeHistoryRecord({
    id: 1,
    eventType: 'grabbed',
    downloadId: 'SABnzbd_nzo_cycle',
    date: '2026-07-05T12:00:00Z',
  }),
];

describe('FRG-UI-010: history screen', () => {
  it('FRG-UI-010 — a grab-and-import cycle renders with type chips, series/issue links, and dates, newest first', async () => {
    const { spy, fetcher } = fakeFetcher(() => pageOf(cycleRecords, { pageSize: 20 }));
    renderWithProviders(<HistoryScreen />, { fetcher });

    await screen.findByTestId('history-row-2');
    expect(spy).toHaveBeenCalledWith(
      '/api/v1/history?page=1&pageSize=20&sortKey=created_at&sortDirection=desc',
    );

    // Server order preserved: imported (newest) row before grabbed.
    const rows = screen.getAllByTestId(/history-row-/);
    expect(rows[0]).toHaveAttribute('data-testid', 'history-row-2');
    expect(rows[1]).toHaveAttribute('data-testid', 'history-row-1');

    const imported = screen.getByTestId('history-row-2');
    expect(within(imported).getByText('Imported')).toBeInTheDocument();
    expect(within(imported).getByRole('link', { name: 'Saga' })).toHaveAttribute(
      'href',
      '/series/1',
    );
    expect(within(imported).getByText('#41')).toBeInTheDocument();
    expect(within(imported).getByText('Jul 5, 2026')).toBeInTheDocument();
    expect(within(screen.getByTestId('history-row-1')).getByText('Grabbed')).toBeInTheDocument();
  });

  it('FRG-UI-010 — filtering to a different event type requests it server-side and hides the cycle', async () => {
    const { spy, fetcher } = fakeFetcher((path) =>
      path.includes('eventType=file_deleted')
        ? pageOf([], { pageSize: 20, totalRecords: 0 })
        : pageOf(cycleRecords, { pageSize: 20 }),
    );
    const user = userEvent.setup();
    renderWithProviders(<HistoryScreen />, { fetcher });

    await screen.findByTestId('history-row-2');
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Filter by event type' }),
      'file_deleted',
    );

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/history?page=1&pageSize=20&sortKey=created_at&sortDirection=desc&eventType=file_deleted',
      ),
    );
    await waitFor(() =>
      expect(screen.queryByTestId('history-row-2')).not.toBeInTheDocument(),
    );
    expect(screen.getByText('No history events.')).toBeInTheDocument();
  });

  it('FRG-UI-010 — an expanded import_blocked event renders its data with the rejection reasons verbatim, never re-sorted', async () => {
    const blocked = makeHistoryRecord({
      id: 5,
      eventType: 'import_blocked',
      data: {
        source_kind: 'download',
        // Deliberately NOT alphabetical — the popover must keep this order.
        reasons: ['Unmapped issue number', 'No series match for parsed title'],
      },
    });
    const { fetcher } = fakeFetcher(() => pageOf([blocked], { pageSize: 20 }));
    const user = userEvent.setup();
    renderWithProviders(<HistoryScreen />, { fetcher });

    await screen.findByTestId('history-row-5');
    expect(within(screen.getByTestId('history-row-5')).getByText('Import Blocked')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Toggle details for event 5' }));
    const details = screen.getByTestId('history-details-5');
    expect(within(details).getByText('source_kind')).toBeInTheDocument();
    expect(within(details).getByText('download')).toBeInTheDocument();

    await user.click(
      within(details).getByRole('button', {
        name: 'Rejection reasons for Saga 041 (2017) (Digital)',
      }),
    );
    const list = await screen.findByTestId('ft-history-reasons-5');
    const items = within(list).getAllByRole('listitem');
    expect(items.map((li) => li.textContent)).toEqual([
      'Unmapped issue number',
      'No series match for parsed title',
    ]);
  });

  it('FRG-UI-010 — pagination is real: page controls fetch page 2 under its own key', async () => {
    const page2Record = makeHistoryRecord({ id: 99, eventType: 'file_renamed' });
    const { spy, fetcher } = fakeFetcher((path) =>
      path.includes('page=2')
        ? pageOf([page2Record], { page: 2, pageSize: 20, totalRecords: 25 })
        : pageOf(cycleRecords, { pageSize: 20, totalRecords: 25 }),
    );
    const user = userEvent.setup();
    renderWithProviders(<HistoryScreen />, { fetcher });

    await screen.findByTestId('history-row-2');
    expect(screen.getByTestId('page-controls-label')).toHaveTextContent('Page 1 of 2');

    await user.click(screen.getByRole('button', { name: 'Next ›' }));

    await screen.findByTestId('history-row-99');
    expect(spy).toHaveBeenCalledWith(
      '/api/v1/history?page=2&pageSize=20&sortKey=created_at&sortDirection=desc',
    );
    expect(screen.getByTestId('page-controls-label')).toHaveTextContent('Page 2 of 2');
    expect(screen.queryByTestId('history-row-2')).not.toBeInTheDocument();
  });

  it('FRG-UI-010 — a queue WS push invalidates history so a new event appears without manual refresh', async () => {
    let calls = 0;
    const { spy, fetcher } = fakeFetcher(() => {
      calls += 1;
      return calls === 1
        ? pageOf([cycleRecords[1]], { pageSize: 20 })
        : pageOf(cycleRecords, { pageSize: 20 });
    });
    const { factory, last } = makeFakeSocketFactory();
    renderWithProviders(
      <>
        <HistoryScreen />
        <WebSocketBridge socketFactory={factory} />
      </>,
      { fetcher },
    );

    await screen.findByTestId('history-row-1');
    expect(spy).toHaveBeenCalledTimes(1);

    act(() => last().emitOpen());
    act(() =>
      last().emitMessage({
        name: 'queue',
        action: 'updated',
        resource: { downloadId: 'SABnzbd_nzo_cycle', status: 'imported' },
      }),
    );

    // The history family is invalidated by the queue push (imports write
    // history rows); the refetched page now shows the imported event.
    await screen.findByTestId('history-row-2');
  });
});
