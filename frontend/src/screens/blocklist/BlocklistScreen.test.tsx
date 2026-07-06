import { describe, it, expect } from 'vitest';
import { screen, waitFor, within, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { makeFakeSocketFactory } from '../../test/fakeSocket';
import { WebSocketBridge } from '../../ws/WebSocketBridge';
import { makeBlocklistRecord, pageOf } from '../../test/mockData';
import type { BlocklistRecord } from '../../api/types';
import { BlocklistScreen } from './BlocklistScreen';

/**
 * FRG-UI-017 — Activity: blocklist screen. Paged banned releases with the ban
 * reason verbatim, per-row removal (release grabbable again), and bulk removal
 * with partial-failure reporting.
 */

describe('FRG-UI-017: blocklist screen', () => {
  it('FRG-UI-017 — a banned release renders source title, series/issue link, indexer, date, and reason verbatim; removing deletes the row', async () => {
    let rows: BlocklistRecord[] = [
      makeBlocklistRecord({
        id: 11,
        sourceTitle: 'Saga 041 scanned',
        message: 'Download failed: archive is corrupt',
      }),
      makeBlocklistRecord({ id: 12, sourceTitle: 'Saga 042 webrip' }),
    ];
    const { spy, fetcher } = fakeFetcher((path, init) => {
      if (init?.method === 'DELETE') {
        const id = Number(path.split('/').pop());
        rows = rows.filter((r) => r.id !== id);
        return undefined;
      }
      return pageOf(rows, { pageSize: 20 });
    });
    const user = userEvent.setup();
    renderWithProviders(<BlocklistScreen />, { fetcher });

    const row = await screen.findByTestId('blocklist-row-11');
    expect(spy).toHaveBeenCalledWith('/api/v1/blocklist?page=1&pageSize=20');
    expect(within(row).getByText('Saga 041 scanned')).toBeInTheDocument();
    expect(within(row).getByRole('link', { name: 'Saga' })).toHaveAttribute(
      'href',
      '/series/1',
    );
    expect(within(row).getByText('#41')).toBeInTheDocument();
    expect(within(row).getByText(/DogNZB/)).toBeInTheDocument();
    expect(within(row).getByText('Jul 4, 2026')).toBeInTheDocument();
    // The ban reason, verbatim.
    expect(
      within(row).getByText('Download failed: archive is corrupt'),
    ).toBeInTheDocument();

    await user.click(
      within(row).getByRole('button', { name: 'Remove Saga 041 scanned' }),
    );
    expect(spy).toHaveBeenCalledWith('/api/v1/blocklist/11', { method: 'DELETE' });
    // The list refetches and the removed row is gone; the sibling stays.
    await waitFor(() =>
      expect(screen.queryByTestId('blocklist-row-11')).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId('blocklist-row-12')).toBeInTheDocument();
  });

  it('FRG-UI-017 — bulk removal deletes the selected rows and reports which removals did not happen', async () => {
    let rows: BlocklistRecord[] = [
      makeBlocklistRecord({ id: 11, sourceTitle: 'Saga 041 scanned' }),
      makeBlocklistRecord({ id: 12, sourceTitle: 'Saga 042 webrip' }),
      makeBlocklistRecord({ id: 13, sourceTitle: 'Saga 043 scanned' }),
    ];
    const { spy, fetcher } = fakeFetcher((path, init) => {
      if (init?.method === 'POST' && path === '/api/v1/blocklist/delete') {
        // Mid-batch partial failure: 12 was already gone.
        rows = rows.filter((r) => r.id !== 11);
        return { deleted: [11], missing: [12] };
      }
      return pageOf(rows, { pageSize: 20 });
    });
    const user = userEvent.setup();
    renderWithProviders(<BlocklistScreen />, { fetcher });

    await screen.findByTestId('blocklist-row-11');
    await user.click(screen.getByRole('checkbox', { name: 'Select Saga 041 scanned' }));
    await user.click(screen.getByRole('checkbox', { name: 'Select Saga 042 webrip' }));
    await user.click(screen.getByRole('button', { name: 'Remove Selected' }));

    expect(spy).toHaveBeenCalledWith('/api/v1/blocklist/delete', {
      method: 'POST',
      body: { ids: [11, 12] },
    });
    // Partial-failure report names the missing ids.
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Removed 1 of 2 entries. Could not remove: 12.',
    );
    // The list refreshed: the deleted row is gone, the others remain.
    await waitFor(() =>
      expect(screen.queryByTestId('blocklist-row-11')).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId('blocklist-row-12')).toBeInTheDocument();
    expect(screen.getByTestId('blocklist-row-13')).toBeInTheDocument();
  });

  it('FRG-UI-017 — select-all selects every row on the page and full bulk success reports nothing', async () => {
    let rows: BlocklistRecord[] = [
      makeBlocklistRecord({ id: 21, sourceTitle: 'A' }),
      makeBlocklistRecord({ id: 22, sourceTitle: 'B' }),
    ];
    const { spy, fetcher } = fakeFetcher((path, init) => {
      if (init?.method === 'POST' && path === '/api/v1/blocklist/delete') {
        rows = [];
        return { deleted: [21, 22], missing: [] };
      }
      return pageOf(rows, { pageSize: 20 });
    });
    const user = userEvent.setup();
    renderWithProviders(<BlocklistScreen />, { fetcher });

    await screen.findByTestId('blocklist-row-21');
    await user.click(
      screen.getByRole('checkbox', { name: 'Select all blocklist entries' }),
    );
    await user.click(screen.getByRole('button', { name: 'Remove Selected' }));

    expect(spy).toHaveBeenCalledWith('/api/v1/blocklist/delete', {
      method: 'POST',
      body: { ids: [21, 22] },
    });
    await screen.findByText('The blocklist is empty.');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('FRG-UI-017 — removing the final page\'s last rows clamps back to the new last page (no false empty state)', async () => {
    const page1 = Array.from({ length: 20 }, (_, i) =>
      makeBlocklistRecord({ id: i + 1, sourceTitle: `P1 ${i + 1}` }),
    );
    let page2: BlocklistRecord[] = [
      makeBlocklistRecord({ id: 21, sourceTitle: 'X 021' }),
      makeBlocklistRecord({ id: 22, sourceTitle: 'X 022' }),
    ];
    const { fetcher } = fakeFetcher((path, init) => {
      if (init?.method === 'POST' && path === '/api/v1/blocklist/delete') {
        const ids = (init.body as { ids: number[] }).ids;
        page2 = page2.filter((r) => !ids.includes(r.id));
        return { deleted: ids, missing: [] };
      }
      const total = page1.length + page2.length;
      return path.includes('page=2')
        ? pageOf(page2, { page: 2, pageSize: 20, totalRecords: total })
        : pageOf(page1, { page: 1, pageSize: 20, totalRecords: total });
    });
    const user = userEvent.setup();
    renderWithProviders(<BlocklistScreen />, { fetcher });

    await screen.findByTestId('blocklist-row-1');
    await user.click(screen.getByRole('button', { name: 'Next ›' }));
    await screen.findByTestId('blocklist-row-21');
    expect(screen.getByTestId('page-controls-label')).toHaveTextContent('Page 2 of 2');

    // Remove EVERY row on the final page.
    await user.click(
      screen.getByRole('checkbox', { name: 'Select all blocklist entries' }),
    );
    await user.click(screen.getByRole('button', { name: 'Remove Selected' }));

    // Instead of a false "Page 2 of 1" over an empty page, the clamp lands us on
    // the real new last page (page 1) with its rows.
    await screen.findByTestId('blocklist-row-1');
    expect(screen.getByTestId('page-controls-label')).toHaveTextContent('Page 1 of 1');
    expect(screen.queryByText('The blocklist is empty.')).not.toBeInTheDocument();
  });

  it('FRG-UI-017 — a genuinely empty blocklist keeps the empty state on page 1 (no clamp)', async () => {
    const { fetcher } = fakeFetcher(() =>
      pageOf([], { pageSize: 20, totalRecords: 0 }),
    );
    renderWithProviders(<BlocklistScreen />, { fetcher });

    expect(await screen.findByText('The blocklist is empty.')).toBeInTheDocument();
    // No page controls render for a zero-record list, and no clamp fires.
    expect(screen.queryByTestId('page-controls-label')).not.toBeInTheDocument();
  });

  it('FRG-UI-017 — a blocklist WS push invalidates the list without manual action', async () => {
    let calls = 0;
    const { fetcher } = fakeFetcher(() => {
      calls += 1;
      return calls === 1
        ? pageOf([makeBlocklistRecord({ id: 11, sourceTitle: 'first' })], {
            pageSize: 20,
          })
        : pageOf(
            [
              makeBlocklistRecord({ id: 11, sourceTitle: 'first' }),
              makeBlocklistRecord({ id: 12, sourceTitle: 'second' }),
            ],
            { pageSize: 20 },
          );
    });
    const { factory, last } = makeFakeSocketFactory();
    renderWithProviders(
      <>
        <BlocklistScreen />
        <WebSocketBridge socketFactory={factory} />
      </>,
      { fetcher },
    );

    await screen.findByTestId('blocklist-row-11');
    expect(screen.queryByTestId('blocklist-row-12')).not.toBeInTheDocument();

    act(() => last().emitOpen());
    // The backend's dedicated blocklist push (a blocklist write) invalidates the
    // family; the refetched page shows the newly-banned release.
    act(() =>
      last().emitMessage({ name: 'blocklist', action: 'updated', resource: null }),
    );

    await screen.findByTestId('blocklist-row-12');
  });

  it('FRG-UI-017 — pagination navigates the server-side envelope', async () => {
    const { spy, fetcher } = fakeFetcher((path) =>
      path.includes('page=2')
        ? pageOf([makeBlocklistRecord({ id: 31 })], {
            page: 2,
            pageSize: 20,
            totalRecords: 22,
          })
        : pageOf([makeBlocklistRecord({ id: 30 })], {
            pageSize: 20,
            totalRecords: 22,
          }),
    );
    const user = userEvent.setup();
    renderWithProviders(<BlocklistScreen />, { fetcher });

    await screen.findByTestId('blocklist-row-30');
    await user.click(screen.getByRole('button', { name: 'Next ›' }));

    await screen.findByTestId('blocklist-row-31');
    expect(spy).toHaveBeenCalledWith('/api/v1/blocklist?page=2&pageSize=20');
    expect(screen.getByTestId('page-controls-label')).toHaveTextContent('Page 2 of 2');
  });
});
