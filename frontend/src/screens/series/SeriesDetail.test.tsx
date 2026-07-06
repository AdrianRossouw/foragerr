import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { makeCommand, mockIssues, mockSeriesResource, pageOf } from '../../test/mockData';
import { queryKeys } from '../../api/queryKeys';
import { useUiStore } from '../../store/uiStore';
import type { SeriesResource } from '../../api/types';
import { SeriesDetail } from './SeriesDetail';

/**
 * FRG-UI-004 — Series detail screen: hero banner with persisted monitored
 * toggle, toolbar commands via POST /command, verbatim-string issue numbers,
 * per-row + bulk monitor toggles, per-row search buttons. Fake fetcher only.
 */

beforeEach(() => {
  useUiStore.setState({ interactiveSearchIssueId: null });
});

/** A stateful fake backend for series 7 covering all detail-screen routes. */
function detailFetcher() {
  return fakeFetcher((path, options) => {
    const method = options?.method ?? 'GET';
    if (method === 'GET' && path === '/api/v1/series/7') return mockSeriesResource;
    if (method === 'GET' && path.startsWith('/api/v1/issues?seriesId=7')) {
      return pageOf(mockIssues);
    }
    if (method === 'PUT' && path === '/api/v1/series/7') {
      return { ...mockSeriesResource, ...(options?.body as object) };
    }
    if (method === 'PUT' && path === '/api/v1/issues/monitor') {
      return options?.body;
    }
    if (method === 'PUT' && path.startsWith('/api/v1/issues/')) {
      const id = Number(path.split('/').pop());
      const issue = mockIssues.find((i) => i.id === id);
      return { ...issue, ...(options?.body as object) };
    }
    if (method === 'POST' && path === '/api/v1/command') {
      const body = options?.body as { name: string };
      return makeCommand({ id: 88, name: body.name, status: 'queued' });
    }
    if (method === 'GET' && path === '/api/v1/command/88') {
      return makeCommand({ id: 88, status: 'started' });
    }
    if (method === 'DELETE' && path.startsWith('/api/v1/series/7')) return undefined;
    throw new Error(`unexpected request: ${method} ${path}`);
  });
}

function renderDetail() {
  const { spy, fetcher } = detailFetcher();
  const utils = renderWithProviders(
    <Routes>
      <Route path="/" element={<div data-testid="library-stub" />} />
      <Route path="/series/:id" element={<SeriesDetail />} />
    </Routes>,
    { fetcher, route: '/series/7' },
  );
  return { spy, ...utils };
}

describe('FRG-UI-004: series detail', () => {
  it('FRG-UI-004 — banner renders cover, path and derived stats; monitored toggle persists via PUT and updates the cache', async () => {
    const { spy, client } = renderDetail();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    expect(screen.getByAltText('Invincible cover')).toHaveAttribute(
      'src',
      '/api/v1/series/7/cover',
    );
    expect(screen.getByText('/comics/Invincible (2003)')).toBeInTheDocument();
    expect(screen.getByText(/4 issues · 2 files · 2 missing/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Unmonitor series' }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series/7', {
        method: 'PUT',
        body: { monitored: false },
      }),
    );
    // The mutation writes the server response into ['series', 7].
    await waitFor(() =>
      expect(
        client.getQueryData<SeriesResource>(queryKeys.series.detail(7))?.monitored,
      ).toBe(false),
    );
    expect(screen.getByRole('button', { name: 'Monitor series' })).toBeInTheDocument();
  });

  it('FRG-UI-004 — toolbar Refresh dispatches POST /command and the button area reflects command status', async () => {
    const { spy } = renderDetail();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Refresh' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/command', {
        method: 'POST',
        body: { name: 'refresh-series', payload: { series_id: 7 } },
      }),
    );
    // Status progresses: the chip polls GET /command/{id} and renders it.
    await waitFor(() =>
      expect(screen.getByTestId('command-status')).toHaveTextContent(
        'Refresh: started',
      ),
    );
  });

  it('FRG-UI-004 — issue numbers 1.5 and 1.MU render verbatim as strings, with file format and size', async () => {
    renderDetail();

    await waitFor(() =>
      expect(screen.getByTestId('issue-row-72')).toBeInTheDocument(),
    );
    expect(within(screen.getByTestId('issue-row-72')).getByText('1.5')).toBeInTheDocument();
    expect(within(screen.getByTestId('issue-row-73')).getByText('1.MU')).toBeInTheDocument();

    // Issue 71 has a CBZ file: format + size render; missing rows say Missing.
    expect(
      within(screen.getByTestId('issue-row-71')).getByText('CBZ · 50.0 MB'),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId('issue-row-72')).getByText('Missing'),
    ).toBeInTheDocument();
  });

  it('FRG-UI-004 — per-row toggle persists one issue; header control bulk-toggles the selected rows', async () => {
    const { spy } = renderDetail();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByTestId('issue-row-72')).toBeInTheDocument(),
    );

    // Single-row toggle: issue "1.5" is monitored -> unmonitor it.
    await user.click(screen.getByRole('button', { name: 'Unmonitor issue 1.5' }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/issues/72', {
        method: 'PUT',
        body: { monitored: false },
      }),
    );
    // Cache patched in place: the same row now offers Monitor.
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Monitor issue 1.5' }),
      ).toBeInTheDocument(),
    );

    // Bulk: select issues 1 (monitored) and 2 (unmonitored), then use the
    // header monitor control -> one atomic PUT for all selected rows.
    await user.click(screen.getByRole('checkbox', { name: 'Select issue 1' }));
    await user.click(screen.getByRole('checkbox', { name: 'Select issue 2' }));
    await user.click(
      screen.getByRole('button', { name: 'Toggle monitored for selected issues' }),
    );
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/issues/monitor', {
        method: 'PUT',
        body: { issue_ids: [71, 74], monitored: true },
      }),
    );
    // Previously-unmonitored issue 2 is now monitored in the cache.
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Unmonitor issue 2' }),
      ).toBeInTheDocument(),
    );
  });

  it("FRG-UI-004 — an issue row's interactive-search button opens the overlay scoped to that issue", async () => {
    renderDetail();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByTestId('issue-row-72')).toBeInTheDocument(),
    );
    await user.click(
      screen.getByRole('button', { name: 'Interactive search for issue 1.5' }),
    );

    const overlay = screen.getByTestId('interactive-search-overlay');
    expect(overlay).toHaveAttribute('data-issue-id', '72');
    expect(useUiStore.getState().interactiveSearchIssueId).toBe(72);

    await user.click(within(overlay).getByRole('button', { name: 'Close' }));
    expect(screen.queryByTestId('interactive-search-overlay')).not.toBeInTheDocument();
  });

  it('FRG-UI-004 — delete dialog offers the delete-files option and issues the DELETE request', async () => {
    const { spy } = renderDetail();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    const dialog = screen.getByRole('dialog', { name: 'Delete Invincible' });
    await user.click(
      within(dialog).getByRole('checkbox', { name: 'Also delete files from disk' }),
    );
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series/7?deleteFiles=true', {
        method: 'DELETE',
      }),
    );
    // Successful delete navigates back to the library index.
    await waitFor(() => expect(screen.getByTestId('library-stub')).toBeInTheDocument());
  });
});
