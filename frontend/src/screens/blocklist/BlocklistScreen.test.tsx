import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
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
