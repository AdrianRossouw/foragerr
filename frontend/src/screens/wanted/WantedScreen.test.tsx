import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { makeCommand, makeWantedRecord, pageOf } from '../../test/mockData';
import { WantedScreen } from './WantedScreen';

/**
 * FRG-UI-011 — Wanted screen: the derived missing list with per-row
 * automatic/interactive search, a Search All backlog-search command whose
 * status stays visible until terminal, an explicit empty state, and real
 * pagination.
 */

const wantedRecords = [
  makeWantedRecord({ id: 72, series_id: 7, issue_number: '1.5', title: 'Interlude', store_date: '2003-02-01', series: { id: 7, title: 'Invincible' } }),
  makeWantedRecord({ id: 73, series_id: 7, issue_number: '1.MU', title: 'Marvel Universe??', store_date: '2003-03-01', series: { id: 7, title: 'Invincible' } }),
];

describe('FRG-UI-011: wanted screen', () => {
  it('FRG-UI-011 — missing issues render with series link, verbatim issue number, and release date; automatic search enqueues an issue search', async () => {
    const { spy, fetcher } = fakeFetcher((path, init) => {
      if (init?.method === 'POST' && path === '/api/v1/command') {
        return makeCommand({ id: 90, name: 'issue-search', status: 'queued' });
      }
      if (path === '/api/v1/command/90') {
        return makeCommand({ id: 90, name: 'issue-search', status: 'started' });
      }
      return pageOf(wantedRecords, { pageSize: 20 });
    });
    const user = userEvent.setup();
    renderWithProviders(<WantedScreen />, { fetcher });

    const row = await screen.findByTestId('wanted-row-72');
    expect(spy).toHaveBeenCalledWith('/api/v1/wanted/missing?page=1&pageSize=20');
    // Verbatim string issue numbers — never numerically coerced.
    expect(within(row).getByText('#1.5')).toBeInTheDocument();
    expect(within(screen.getByTestId('wanted-row-73')).getByText('#1.MU')).toBeInTheDocument();
    expect(within(row).getByRole('link', { name: 'Invincible' })).toHaveAttribute(
      'href',
      '/series/7',
    );
    expect(within(row).getByText('Feb 1, 2003')).toBeInTheDocument();

    await user.click(
      within(row).getByRole('button', { name: 'Automatic search for issue 1.5' }),
    );
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/command', {
        method: 'POST',
        body: { name: 'issue-search', payload: { series_id: 7, issue_id: 72 } },
      }),
    );
  });

  it('FRG-UI-011 — the interactive-search action opens the existing overlay scoped to the issue', async () => {
    const { fetcher } = fakeFetcher((path) => {
      if (path.startsWith('/api/v1/release')) return [];
      return pageOf(wantedRecords, { pageSize: 20 });
    });
    const user = userEvent.setup();
    renderWithProviders(<WantedScreen />, { fetcher });

    await screen.findByTestId('wanted-row-72');
    await user.click(
      screen.getByRole('button', { name: 'Interactive search for issue 1.5' }),
    );

    const overlay = screen.getByTestId('interactive-search-overlay');
    expect(overlay).toHaveAttribute('data-issue-id', '72');
  });

  it('FRG-UI-011 — Search All enqueues one backlog-search command and its status stays visible until terminal', async () => {
    let wantedCalls = 0;
    const { spy, fetcher } = fakeFetcher((path, init) => {
      if (init?.method === 'POST' && path === '/api/v1/command') {
        return makeCommand({ id: 99, name: 'backlog-search', status: 'queued' });
      }
      if (path === '/api/v1/command/99') {
        return makeCommand({
          id: 99,
          name: 'backlog-search',
          status: 'completed',
          finished_at: '2026-07-05T12:01:00Z',
        });
      }
      if (path.startsWith('/api/v1/wanted/missing')) {
        wantedCalls += 1;
        return pageOf(wantedRecords, { pageSize: 20 });
      }
      throw new Error(`unexpected request: ${path}`);
    });
    const user = userEvent.setup();
    renderWithProviders(<WantedScreen />, { fetcher });

    await screen.findByTestId('wanted-row-72');
    await user.click(screen.getByRole('button', { name: 'Search All' }));

    expect(spy).toHaveBeenCalledWith('/api/v1/command', {
      method: 'POST',
      body: { name: 'backlog-search', payload: null },
    });
    // The terminal status stays visible on the chip (watched until terminal).
    await waitFor(() =>
      expect(screen.getByTestId('command-status')).toHaveTextContent(
        'Search All: completed',
      ),
    );
    // A completed search may have grabbed releases: the wanted list refetched.
    await waitFor(() => expect(wantedCalls).toBe(2));
  });

  it('FRG-UI-011 — the empty state is explicit and distinct from loading/error', async () => {
    const { fetcher } = fakeFetcher(() => pageOf([], { pageSize: 20 }));
    renderWithProviders(<WantedScreen />, { fetcher });

    expect(
      await screen.findByText('Nothing is missing — every monitored issue has a file.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('Loading wanted issues…')).not.toBeInTheDocument();
    expect(screen.queryByText('Could not load wanted issues.')).not.toBeInTheDocument();
  });

  it('FRG-UI-011 — pagination navigates the server-side envelope', async () => {
    const { spy, fetcher } = fakeFetcher((path) =>
      path.includes('page=2')
        ? pageOf([makeWantedRecord({ id: 88 })], { page: 2, pageSize: 20, totalRecords: 21 })
        : pageOf(wantedRecords, { pageSize: 20, totalRecords: 21 }),
    );
    const user = userEvent.setup();
    renderWithProviders(<WantedScreen />, { fetcher });

    await screen.findByTestId('wanted-row-72');
    await user.click(screen.getByRole('button', { name: 'Next ›' }));

    await screen.findByTestId('wanted-row-88');
    expect(spy).toHaveBeenCalledWith('/api/v1/wanted/missing?page=2&pageSize=20');
    expect(screen.getByTestId('page-controls-label')).toHaveTextContent('Page 2 of 2');
  });
});
