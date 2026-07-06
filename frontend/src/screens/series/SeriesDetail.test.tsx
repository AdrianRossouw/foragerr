import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import {
  makeCommand,
  makeMediaManagementConfig,
  mockIssues,
  mockSeriesResource,
  pageOf,
} from '../../test/mockData';
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
function detailFetcher(mmConfig = makeMediaManagementConfig(), deleteCmdStatus = 'completed') {
  return fakeFetcher((path, options) => {
    const method = options?.method ?? 'GET';
    if (method === 'GET' && path === '/api/v1/config/mediamanagement') {
      return mmConfig;
    }
    if (method === 'DELETE' && path === '/api/v1/issuefile/501') {
      return { recycled: mmConfig.recycle_bin_path || null };
    }
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
    // The delete-series-files command watched by the deleteFiles path (202).
    if (method === 'GET' && path === '/api/v1/command/77') {
      return makeCommand({ id: 77, name: 'delete-series-files', status: deleteCmdStatus });
    }
    if (method === 'DELETE' && path.startsWith('/api/v1/series/7')) {
      // deleteFiles=true → 202 + the enqueued delete-series-files command;
      // plain delete → 204 (no body).
      return path.includes('deleteFiles=true')
        ? makeCommand({ id: 77, name: 'delete-series-files', status: 'queued' })
        : undefined;
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  });
}

function renderDetail(mmConfig = makeMediaManagementConfig(), deleteCmdStatus = 'completed') {
  const { spy, fetcher } = detailFetcher(mmConfig, deleteCmdStatus);
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

  it('FRG-UI-004 — delete-with-files enqueues the delete-series-files command (202) and navigates once it completes', async () => {
    const { spy } = renderDetail();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    const dialog = screen.getByRole('dialog', { name: 'Delete Invincible' });
    // Truthful since m2-daily-surfaces: deleteFiles=true is implemented — the
    // dialog states the real consequence instead of a 501-era caveat.
    expect(
      within(dialog).getByText(
        /Files are moved to the recycle bin when one is configured; otherwise they are permanently deleted\./,
      ),
    ).toBeInTheDocument();
    await user.click(
      within(dialog).getByRole('checkbox', { name: 'Also delete files from disk' }),
    );
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series/7?deleteFiles=true', {
        method: 'DELETE',
      }),
    );
    // The 202 returns a watched command; navigation waits for its completion.
    await waitFor(() => expect(screen.getByTestId('library-stub')).toBeInTheDocument());
  });

  it('FRG-UI-004 — plain delete (no files) is a 204 and navigates immediately without watching a command', async () => {
    const { spy } = renderDetail();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    // Leave the "Also delete files" box unchecked → deleteFiles=false.
    await user.click(
      within(screen.getByRole('dialog', { name: 'Delete Invincible' })).getByRole(
        'button',
        { name: 'Delete' },
      ),
    );

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series/7?deleteFiles=false', {
        method: 'DELETE',
      }),
    );
    await waitFor(() => expect(screen.getByTestId('library-stub')).toBeInTheDocument());
    // No delete-series-files command was polled on the plain path.
    expect(spy).not.toHaveBeenCalledWith('/api/v1/command/77');
  });

  it('FRG-UI-004 — delete-with-files shows the delete-series-files command status while it runs', async () => {
    // Hold the command non-terminal ('started'): the dialog reflects its status
    // and does NOT navigate away until it reaches a terminal state.
    const { spy } = renderDetail(makeMediaManagementConfig(), 'started');
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
    // The watched command's live status is surfaced in the dialog…
    await waitFor(() =>
      expect(screen.getByTestId('delete-command-status')).toHaveTextContent(
        'Deleting files: started',
      ),
    );
    // …and we have NOT navigated away while it is still running.
    expect(screen.queryByTestId('library-stub')).not.toBeInTheDocument();
  });

  it('FRG-UI-004 — delete-file confirmation names the recycle bin when one is configured and deletes via /api/v1/issuefile', async () => {
    const { spy } = renderDetail(
      makeMediaManagementConfig({ recycle_bin_path: '/recycle' }),
    );
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByTestId('issue-row-71')).toBeInTheDocument(),
    );
    // Only rows WITH a file offer the delete-file action.
    expect(
      screen.getByRole('button', { name: 'Delete file for issue 1' }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Delete file for issue 1.5' }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Delete file for issue 1' }));
    const dialog = await screen.findByRole('dialog', {
      name: 'Delete file for issue 1',
    });
    expect(
      within(dialog).getByText('/comics/Invincible (2003)/Invincible 001.cbz'),
    ).toBeInTheDocument();
    // The confirmation names the consequence: recycle bin, not permanent.
    expect(
      await within(dialog).findByText('This moves the file to the recycle bin.'),
    ).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Delete File' }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/issuefile/501', {
        method: 'DELETE',
      }),
    );
    // Success closes the confirmation.
    await waitFor(() =>
      expect(
        screen.queryByRole('dialog', { name: 'Delete file for issue 1' }),
      ).not.toBeInTheDocument(),
    );
  });

  it('FRG-UI-004 — delete-file confirmation warns of permanent deletion when no recycle bin is configured', async () => {
    renderDetail(makeMediaManagementConfig({ recycle_bin_path: '' }));
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByTestId('issue-row-71')).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Delete file for issue 1' }));
    const dialog = await screen.findByRole('dialog', {
      name: 'Delete file for issue 1',
    });

    expect(
      await within(dialog).findByText(
        'This permanently deletes the file from disk — no recycle bin is configured.',
      ),
    ).toBeInTheDocument();
  });

  it('FRG-UI-004 — delete-file dialog: a media-config fetch error disables Delete and offers a retry that re-enables it', async () => {
    let mmFails = true;
    const { fetcher } = fakeFetcher((path, options) => {
      const method = options?.method ?? 'GET';
      if (method === 'GET' && path === '/api/v1/config/mediamanagement') {
        if (mmFails) throw new Error('config unavailable');
        return makeMediaManagementConfig({ recycle_bin_path: '/recycle' });
      }
      if (method === 'GET' && path === '/api/v1/series/7') return mockSeriesResource;
      if (method === 'GET' && path.startsWith('/api/v1/issues?seriesId=7')) {
        return pageOf(mockIssues);
      }
      if (method === 'DELETE' && path === '/api/v1/issuefile/501') {
        return { recycled: '/recycle' };
      }
      throw new Error(`unexpected request: ${method} ${path}`);
    });
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/" element={<div data-testid="library-stub" />} />
        <Route path="/series/:id" element={<SeriesDetail />} />
      </Routes>,
      { fetcher, route: '/series/7' },
    );

    await waitFor(() =>
      expect(screen.getByTestId('issue-row-71')).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Delete file for issue 1' }));
    const dialog = await screen.findByRole('dialog', {
      name: 'Delete file for issue 1',
    });

    // Config errored → the consequence is unknown, so Delete File is disabled
    // (matching its comment) and an explicit Retry is offered.
    expect(
      await within(dialog).findByText(
        /Could not read the recycle-bin configuration/,
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole('button', { name: 'Delete File' }),
    ).toBeDisabled();

    mmFails = false;
    await user.click(within(dialog).getByRole('button', { name: 'Retry' }));

    // A successful retry resolves the consequence and re-enables Delete File.
    expect(
      await within(dialog).findByText('This moves the file to the recycle bin.'),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        within(dialog).getByRole('button', { name: 'Delete File' }),
      ).toBeEnabled(),
    );
  });
});
