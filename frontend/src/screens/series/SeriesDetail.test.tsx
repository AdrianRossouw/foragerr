import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import {
  makeCommand,
  makeIssue,
  makeMediaManagementConfig,
  makeSeriesResource,
  mockIssues,
  mockSeriesResource,
  pageOf,
} from '../../test/mockData';
import { queryKeys } from '../../api/queryKeys';
import { useUiStore } from '../../store/uiStore';
import type {
  CollectionRecord,
  IssueResource,
  SeriesResource,
} from '../../api/types';
import { SeriesDetail } from './SeriesDetail';

/**
 * FRG-UI-004 — M4 series detail: blurred local-cover hero, icon-over-label
 * action row, verbatim issue numbers, status pills + collected-in chips, and
 * show-more overview. FRG-UI-025 — bulk selection (shift-range, select-all,
 * labeled action bar). FRG-UI-026 — collections tab + containment dialog.
 * Fake fetcher only; no live backend.
 */

beforeEach(() => {
  useUiStore.setState({ interactiveSearchIssueId: null });
});

interface DetailOptions {
  mmConfig?: ReturnType<typeof makeMediaManagementConfig>;
  deleteCmdStatus?: string;
  series?: SeriesResource;
  issues?: IssueResource[];
  collections?: CollectionRecord[];
}

/** A stateful fake backend for series 7 covering all detail-screen routes. */
function detailFetcher({
  mmConfig = makeMediaManagementConfig(),
  deleteCmdStatus = 'completed',
  series = mockSeriesResource,
  issues = mockIssues,
  collections = [],
}: DetailOptions = {}) {
  return fakeFetcher((path, options) => {
    const method = options?.method ?? 'GET';
    if (method === 'GET' && path === '/api/v1/config/mediamanagement') {
      return mmConfig;
    }
    if (method === 'DELETE' && path === '/api/v1/issuefile/501') {
      return { recycled: mmConfig.recycle_bin_path || null };
    }
    if (method === 'GET' && path === '/api/v1/series/7') return series;
    if (method === 'GET' && path === '/api/v1/series/7/collections') {
      return { records: collections };
    }
    if (method === 'GET' && path.startsWith('/api/v1/issues?seriesId=7')) {
      return pageOf(issues);
    }
    if (method === 'PUT' && path === '/api/v1/series/7') {
      return { ...series, ...(options?.body as object) };
    }
    if (method === 'PUT' && path === '/api/v1/issues/monitor') {
      return options?.body;
    }
    if (method === 'PUT' && path.startsWith('/api/v1/issues/')) {
      const id = Number(path.split('/').pop());
      const issue = issues.find((i) => i.id === id);
      return { ...issue, ...(options?.body as object) };
    }
    if (method === 'POST' && path === '/api/v1/command') {
      const body = options?.body as { name: string };
      return makeCommand({ id: 88, name: body.name, status: 'queued' });
    }
    if (method === 'GET' && path === '/api/v1/command/88') {
      return makeCommand({ id: 88, status: 'started' });
    }
    if (method === 'GET' && path === '/api/v1/command/77') {
      return makeCommand({ id: 77, name: 'delete-series-files', status: deleteCmdStatus });
    }
    if (method === 'GET' && path === '/api/v1/rename?seriesId=7') {
      return [];
    }
    if (method === 'GET' && path.startsWith('/api/v1/command?page=1')) {
      return pageOf([]);
    }
    if (method === 'DELETE' && path.startsWith('/api/v1/series/7')) {
      return path.includes('deleteFiles=true')
        ? makeCommand({ id: 77, name: 'delete-series-files', status: 'queued' })
        : undefined;
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  });
}

function renderDetail(options: DetailOptions = {}) {
  const { spy, fetcher } = detailFetcher(options);
  const utils = renderWithProviders(
    <Routes>
      <Route path="/" element={<div data-testid="library-stub" />} />
      <Route path="/series/90" element={<div data-testid="nav-90" />} />
      <Route path="/series/:id" element={<SeriesDetail />} />
    </Routes>,
    { fetcher, route: '/series/7' },
  );
  return { spy, ...utils };
}

describe('FRG-UI-004: series detail hero + issues table', () => {
  it('FRG-UI-004 — hero renders from the local cover with a meta row and a monitored toggle that persists via PUT', async () => {
    const { spy, client } = renderDetail();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    // Sharp cover comes exclusively from the local cover endpoint, versioned
    // by cover_cached_at (FRG-UI-003).
    expect(screen.getByAltText('Invincible cover')).toHaveAttribute(
      'src',
      `/api/v1/series/7/cover?v=${encodeURIComponent('2026-07-01T00:00:00Z')}`,
    );
    // Meta row: monitored label, publisher, issue count.
    expect(screen.getByText('Monitored')).toBeInTheDocument();
    expect(screen.getByText('Image')).toBeInTheDocument();
    expect(screen.getByText('4 issues')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Unmonitor series' }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series/7', {
        method: 'PUT',
        body: { monitored: false },
      }),
    );
    await waitFor(() =>
      expect(
        client.getQueryData<SeriesResource>(queryKeys.series.detail(7))?.monitored,
      ).toBe(false),
    );
    expect(screen.getByRole('button', { name: 'Monitor series' })).toBeInTheDocument();
  });

  it('FRG-UI-004 — a series with no cached cover renders no sharp <img> in the hero', async () => {
    renderDetail({ series: { ...mockSeriesResource, cover_cached_at: null } });

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    expect(screen.queryByAltText('Invincible cover')).not.toBeInTheDocument();
  });

  it('FRG-UI-004 — the action row Refresh button dispatches POST /command and surfaces command status', async () => {
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
    await waitFor(() =>
      expect(screen.getByTestId('command-status')).toHaveTextContent('Refresh: started'),
    );
  });

  it('FRG-UI-004 — the Search All hero action dispatches series-search with monitored_only: false', async () => {
    const { spy } = renderDetail();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Search All' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/command', {
        method: 'POST',
        body: {
          name: 'series-search',
          payload: { series_id: 7, monitored_only: false },
        },
      }),
    );
  });

  it('FRG-UI-004 — the Search Monitored hero action dispatches series-search scoped to today\'s wanted set', async () => {
    const { spy } = renderDetail();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Search Monitored' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/command', {
        method: 'POST',
        body: { name: 'series-search', payload: { series_id: 7 } },
      }),
    );
  });

  it('FRG-UI-004 — the overflow menu Rescan item dispatches scan-series', async () => {
    const { spy } = renderDetail();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'More' }));
    expect(screen.getByTestId('series-overflow-menu')).toBeInTheDocument();
    await user.click(screen.getByRole('menuitem', { name: 'Rescan' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/command', {
        method: 'POST',
        body: { name: 'scan-series', payload: { series_id: 7 } },
      }),
    );
    // The menu closes after dispatch.
    expect(screen.queryByTestId('series-overflow-menu')).not.toBeInTheDocument();
  });

  it('FRG-UI-004 — the overflow menu Rename Files item opens the rename preview panel', async () => {
    renderDetail();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'More' }));
    await user.click(screen.getByRole('menuitem', { name: 'Rename Files' }));

    expect(
      await screen.findByRole('dialog', { name: 'Rename preview — Invincible' }),
    ).toBeInTheDocument();
  });

  it('FRG-UI-004 — issue numbers 1.5 and 1.MU render verbatim as strings, never coerced', async () => {
    renderDetail();

    await waitFor(() =>
      expect(screen.getByTestId('issue-row-72')).toBeInTheDocument(),
    );
    expect(within(screen.getByTestId('issue-row-72')).getByText('1.5')).toBeInTheDocument();
    expect(within(screen.getByTestId('issue-row-73')).getByText('1.MU')).toBeInTheDocument();
  });

  it('FRG-UI-004 — issues table anatomy: status pills, size, and collected-in chips', async () => {
    const issues: IssueResource[] = [
      makeIssue({
        id: 71,
        issue_number: '1',
        has_file: true,
        file: { id: 501, path: '/comics/Invincible/Invincible 001.cbz', size: 52_428_800 },
        collected_in: [
          {
            trade_series_id: 90,
            trade_series_title: 'Invincible Compendium One',
            trade_issue_id: 900,
            booktype: 'tpb',
            range_label: '1-8',
          },
        ],
      }),
      makeIssue({ id: 72, issue_number: '2', cover_date: '2003-02-01' }),
      makeIssue({ id: 73, issue_number: '3', cover_date: '2999-01-01' }),
    ];
    renderDetail({ issues });

    await waitFor(() =>
      expect(screen.getByTestId('issue-row-71')).toBeInTheDocument(),
    );
    const owned = within(screen.getByTestId('issue-row-71'));
    expect(owned.getByText('Downloaded')).toBeInTheDocument();
    expect(owned.getByText('50.0 MB')).toBeInTheDocument();
    expect(owned.getByText('1-8')).toBeInTheDocument(); // collected-in chip

    // Released (past) with no file → Missing; future-dated → Unreleased.
    expect(within(screen.getByTestId('issue-row-72')).getByText('Missing')).toBeInTheDocument();
    expect(
      within(screen.getByTestId('issue-row-73')).getByText('Unreleased'),
    ).toBeInTheDocument();
    // File-less rows show an em dash for size.
    expect(within(screen.getByTestId('issue-row-72')).getByText('—')).toBeInTheDocument();
  });

  it('FRG-UI-004 — existing per-issue flows survive: monitor toggle, automatic search, interactive overlay', async () => {
    const { spy } = renderDetail();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByTestId('issue-row-72')).toBeInTheDocument(),
    );

    await user.click(screen.getByRole('button', { name: 'Unmonitor issue 1.5' }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/issues/72', {
        method: 'PUT',
        body: { monitored: false },
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Monitor issue 1.5' })).toBeInTheDocument(),
    );

    await user.click(screen.getByRole('button', { name: 'Automatic search for issue 1.5' }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/command', {
        method: 'POST',
        body: { name: 'issue-search', payload: { series_id: 7, issue_id: 72 } },
      }),
    );

    await user.click(screen.getByRole('button', { name: 'Interactive search for issue 1.5' }));
    const overlay = screen.getByTestId('interactive-search-overlay');
    expect(overlay).toHaveAttribute('data-issue-id', '72');
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
    await user.click(
      within(dialog).getByRole('checkbox', { name: 'Also delete files from disk' }),
    );
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series/7?deleteFiles=true', {
        method: 'DELETE',
      }),
    );
    await waitFor(() => expect(screen.getByTestId('library-stub')).toBeInTheDocument());
  });

  it('FRG-UI-004 — plain delete (no files) is a 204 and navigates immediately', async () => {
    const { spy } = renderDetail();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await user.click(
      within(screen.getByRole('dialog', { name: 'Delete Invincible' })).getByRole('button', {
        name: 'Delete',
      }),
    );

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series/7?deleteFiles=false', {
        method: 'DELETE',
      }),
    );
    await waitFor(() => expect(screen.getByTestId('library-stub')).toBeInTheDocument());
    expect(spy).not.toHaveBeenCalledWith('/api/v1/command/77');
  });

  it('FRG-UI-004 — delete-with-files shows the delete-series-files command status while it runs', async () => {
    const { spy } = renderDetail({ deleteCmdStatus: 'started' });
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
    await waitFor(() =>
      expect(screen.getByTestId('delete-command-status')).toHaveTextContent(
        'Deleting files: started',
      ),
    );
    expect(screen.queryByTestId('library-stub')).not.toBeInTheDocument();
  });

  it('FRG-UI-004 — delete-file confirmation names the recycle bin and deletes via /api/v1/issuefile', async () => {
    const { spy } = renderDetail({
      mmConfig: makeMediaManagementConfig({ recycle_bin_path: '/recycle' }),
    });
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByTestId('issue-row-71')).toBeInTheDocument());
    expect(
      screen.getByRole('button', { name: 'Delete file for issue 1' }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Delete file for issue 1.5' }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Delete file for issue 1' }));
    const dialog = await screen.findByRole('dialog', { name: 'Delete file for issue 1' });
    expect(
      within(dialog).getByText('/comics/Invincible (2003)/Invincible 001.cbz'),
    ).toBeInTheDocument();
    expect(
      await within(dialog).findByText('This moves the file to the recycle bin.'),
    ).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Delete File' }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/issuefile/501', { method: 'DELETE' }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole('dialog', { name: 'Delete file for issue 1' }),
      ).not.toBeInTheDocument(),
    );
  });

  it('FRG-UI-004 — delete-file confirmation warns of permanent deletion when no recycle bin is configured', async () => {
    renderDetail({ mmConfig: makeMediaManagementConfig({ recycle_bin_path: '' }) });
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByTestId('issue-row-71')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Delete file for issue 1' }));
    const dialog = await screen.findByRole('dialog', { name: 'Delete file for issue 1' });
    expect(
      await within(dialog).findByText(
        'This permanently deletes the file from disk — no recycle bin is configured.',
      ),
    ).toBeInTheDocument();
  });

  it('FRG-UI-004 — delete-file dialog: a config fetch error disables Delete and offers a retry that re-enables it', async () => {
    let mmFails = true;
    const { fetcher } = fakeFetcher((path, options) => {
      const method = options?.method ?? 'GET';
      if (method === 'GET' && path === '/api/v1/config/mediamanagement') {
        if (mmFails) throw new Error('config unavailable');
        return makeMediaManagementConfig({ recycle_bin_path: '/recycle' });
      }
      if (method === 'GET' && path === '/api/v1/series/7') return mockSeriesResource;
      if (method === 'GET' && path === '/api/v1/series/7/collections') return { records: [] };
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

    await waitFor(() => expect(screen.getByTestId('issue-row-71')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Delete file for issue 1' }));
    const dialog = await screen.findByRole('dialog', { name: 'Delete file for issue 1' });

    expect(
      await within(dialog).findByText(/Could not read the recycle-bin configuration/),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Delete File' })).toBeDisabled();

    mmFails = false;
    await user.click(within(dialog).getByRole('button', { name: 'Retry' }));
    expect(
      await within(dialog).findByText('This moves the file to the recycle bin.'),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: 'Delete File' })).toBeEnabled(),
    );
  });
});

/**
 * FRG-UI-004 — show-more overview: the toggle appears only when the clamped
 * paragraph actually overflows (measured, not char-counted). jsdom does no
 * layout, so scrollHeight/clientHeight and ResizeObserver are mocked.
 */
describe('FRG-UI-004: show-more overview', () => {
  let restore: (() => void) | null = null;

  function mockMetrics(scroll: number, client: number) {
    const scrollDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollHeight');
    const clientDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset?.testid === 'series-overview' ? scroll : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset?.testid === 'series-overview' ? client : 0;
      },
    });
    (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
    restore = () => {
      if (scrollDesc) Object.defineProperty(HTMLElement.prototype, 'scrollHeight', scrollDesc);
      if (clientDesc) Object.defineProperty(HTMLElement.prototype, 'clientHeight', clientDesc);
    };
  }

  afterEach(() => {
    restore?.();
    restore = null;
  });

  it('FRG-UI-004 — a long overview clamps behind a show-more toggle that expands and collapses', async () => {
    mockMetrics(240, 100);
    const user = userEvent.setup();
    renderDetail({
      series: { ...mockSeriesResource, description_sanitized: 'A very long overview. '.repeat(40) },
    });

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    const toggle = await screen.findByRole('button', { name: 'Show more' });
    await user.click(toggle);
    expect(screen.getByRole('button', { name: 'Show less' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Show less' }));
    expect(screen.getByRole('button', { name: 'Show more' })).toBeInTheDocument();
  });

  it('FRG-UI-004 — a short overview shows no show-more control', async () => {
    mockMetrics(80, 100);
    renderDetail({ series: { ...mockSeriesResource, description_sanitized: 'Short.' } });

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    expect(screen.queryByRole('button', { name: 'Show more' })).not.toBeInTheDocument();
  });
});

/** FRG-UI-025 — issue bulk selection and actions. */
describe('FRG-UI-025: bulk selection', () => {
  it('FRG-UI-025 — shift-click selects the span between the anchor and the shift-clicked row', async () => {
    renderDetail();
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByTestId('issue-row-71')).toBeInTheDocument());
    await user.click(screen.getByRole('checkbox', { name: 'Select issue 1' }));
    await user.keyboard('{Shift>}');
    await user.click(screen.getByRole('checkbox', { name: 'Select issue 2' }));
    await user.keyboard('{/Shift}');

    // Rows 1, 1.5, 1.MU, 2 all selected → the action bar reads the count.
    const bar = screen.getByRole('region', { name: 'Bulk issue actions' });
    expect(within(bar).getByText('4 selected')).toBeInTheDocument();
    for (const name of ['Select issue 1', 'Select issue 1.5', 'Select issue 1.MU', 'Select issue 2']) {
      expect(screen.getByRole('checkbox', { name })).toBeChecked();
    }
  });

  it('FRG-UI-025 — the header checkbox selects all rows and then deselects them', async () => {
    renderDetail();
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByTestId('issue-row-71')).toBeInTheDocument());
    await user.click(screen.getByRole('checkbox', { name: 'Select all issues' }));
    expect(screen.getByText('4 selected')).toBeInTheDocument();

    await user.click(screen.getByRole('checkbox', { name: 'Select all issues' }));
    expect(
      screen.queryByRole('region', { name: 'Bulk issue actions' }),
    ).not.toBeInTheDocument();
  });

  it('FRG-UI-025 — Monitor selected applies the bulk mutation and clears the selection', async () => {
    const { spy } = renderDetail();
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByTestId('issue-row-71')).toBeInTheDocument());
    await user.click(screen.getByRole('checkbox', { name: 'Select issue 1' }));
    await user.click(screen.getByRole('checkbox', { name: 'Select issue 2' }));
    await user.click(screen.getByRole('button', { name: 'Monitor selected' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/issues/monitor', {
        method: 'PUT',
        body: { issue_ids: [71, 74], monitored: true },
      }),
    );
    // Previously-unmonitored issue 2 is now monitored, and the bar has cleared.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Unmonitor issue 2' })).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole('region', { name: 'Bulk issue actions' }),
    ).not.toBeInTheDocument();
  });

  it('FRG-UI-025 — Search selected dispatches one automatic-search command per row, sequentially', async () => {
    const { spy } = renderDetail();
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByTestId('issue-row-71')).toBeInTheDocument());
    await user.click(screen.getByRole('checkbox', { name: 'Select issue 1' }));
    await user.click(screen.getByRole('checkbox', { name: 'Select issue 2' }));
    await user.click(screen.getByRole('button', { name: 'Search selected' }));

    await waitFor(() => {
      const searchIds = spy.mock.calls
        .filter(
          ([path, init]) =>
            path === '/api/v1/command' &&
            (init?.body as { name?: string })?.name === 'issue-search',
        )
        .map(([, init]) => (init?.body as { payload: { issue_id: number } }).payload.issue_id);
      expect(searchIds).toEqual([71, 74]);
    });
    await waitFor(() =>
      expect(screen.getByTestId('command-status')).toHaveTextContent(/Search selected/),
    );
  });
});

/** FRG-UI-026 — collections tab + containment dialog. */
describe('FRG-UI-026: collections tab', () => {
  const collections: CollectionRecord[] = [
    {
      trade_issue_id: 900,
      trade_series_id: 90,
      trade_series_title: 'Invincible Compendium One',
      booktype: 'tpb',
      release_date: '2011-09-01',
      ranges: [{ target_series_id: 7, label: '1-8' }],
      coverage: 'collected',
      issues_in_ranges: 8,
      owned_in_ranges: 8,
    },
    {
      trade_issue_id: 901,
      trade_series_id: 90,
      trade_series_title: 'Invincible TPB Vol 2',
      booktype: 'tpb',
      release_date: '2004-01-01',
      ranges: [{ target_series_id: 7, label: '9-13' }],
      coverage: 'partial',
      issues_in_ranges: 5,
      owned_in_ranges: 2,
    },
  ];

  it('FRG-UI-026 — the collections list renders format chips, range labels, and coverage pills with the right count', async () => {
    renderDetail({ collections });
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('radio', { name: 'Collections · 2' }));

    expect(screen.getByText('Invincible Compendium One')).toBeInTheDocument();
    expect(screen.getByText('Invincible TPB Vol 2')).toBeInTheDocument();
    expect(screen.getByText(/Collects 1-8 · 8 issues · owned 8/)).toBeInTheDocument();
    expect(screen.getByTestId('coverage-900')).toHaveTextContent('Collected');
    expect(screen.getByTestId('coverage-901')).toHaveTextContent('Partial');

    // Open navigates to the collecting trade series' detail.
    await user.click(screen.getByRole('button', { name: 'Open Invincible Compendium One' }));
    expect(screen.getByTestId('nav-90')).toBeInTheDocument();
  });

  it('FRG-UI-026 — an empty collections tab shows an honest empty state and a 0 count', async () => {
    renderDetail({ collections: [] });
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('radio', { name: 'Collections · 0' }));
    expect(screen.getByTestId('collections-empty')).toBeInTheDocument();
  });

  it('FRG-UI-026 — declaring containment from the dialog round-trips a replace-all PUT without touching monitored state', async () => {
    const tradeSeries = makeSeriesResource({
      id: 7,
      title: 'Invincible TPB',
      sort_title: 'invincible tpb',
      booktype: 'tpb',
    });
    const tradeIssues: IssueResource[] = [
      makeIssue({ id: 900, series_id: 7, issue_number: '1', title: 'Volume One', has_file: false, file: null }),
    ];
    const targetIssues: IssueResource[] = [
      makeIssue({ id: 51, series_id: 5, issue_number: '1' }),
      makeIssue({ id: 52, series_id: 5, issue_number: '2' }),
      makeIssue({ id: 53, series_id: 5, issue_number: '3' }),
    ];
    const libraryIndex = [
      tradeSeries,
      makeSeriesResource({ id: 5, title: 'Invincible', sort_title: 'invincible', booktype: null }),
    ];

    const { spy, fetcher } = fakeFetcher((path, options) => {
      const method = options?.method ?? 'GET';
      if (method === 'GET' && path === '/api/v1/series/7') return tradeSeries;
      if (method === 'GET' && path === '/api/v1/series/7/collections') return { records: [] };
      if (method === 'GET' && path.startsWith('/api/v1/issues?seriesId=7')) {
        return pageOf(tradeIssues);
      }
      if (method === 'GET' && path.startsWith('/api/v1/series?')) return pageOf(libraryIndex);
      if (method === 'GET' && path.startsWith('/api/v1/issues?seriesId=5')) {
        return pageOf(targetIssues);
      }
      if (method === 'PUT' && path === '/api/v1/issues/900/collections') return {};
      throw new Error(`unexpected request: ${method} ${path}`);
    });
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/series/:id" element={<SeriesDetail />} />
      </Routes>,
      { fetcher, route: '/series/7' },
    );

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible TPB' })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('radio', { name: 'Collections · 0' }));
    await user.click(screen.getByRole('button', { name: 'Declare contents for Volume One' }));

    const dialog = await screen.findByRole('dialog', { name: 'Declare contents' });
    await user.selectOptions(within(dialog).getByLabelText('Target series'), '5');
    await user.selectOptions(within(dialog).getByLabelText('Range 1 start issue'), '51');
    await user.selectOptions(within(dialog).getByLabelText('Range 1 end issue'), '52');
    await user.click(within(dialog).getByRole('button', { name: /Add sub-range/ }));
    await user.selectOptions(within(dialog).getByLabelText('Range 2 start issue'), '53');
    await user.selectOptions(within(dialog).getByLabelText('Range 2 end issue'), '53');
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/issues/900/collections', {
        method: 'PUT',
        body: {
          ranges: [
            { target_series_id: 5, start_issue_id: 51, end_issue_id: 52 },
            { target_series_id: 5, start_issue_id: 53, end_issue_id: 53 },
          ],
        },
      }),
    );
    // Declaration is display-only — no monitor/wanted writes happened.
    expect(spy).not.toHaveBeenCalledWith('/api/v1/issues/monitor', expect.anything());
  });
});

/**
 * FRG-UI-022 — collected-edition badge on the hero: a typed series shows a
 * book-type badge; a null-typed single-issues run shows none.
 */
function renderDetailWithBooktype(booktype: SeriesResource['booktype']) {
  const series = makeSeriesResource({
    id: 7,
    title: 'Invincible',
    sort_title: 'invincible',
    booktype,
  });
  const fetcher = fakeFetcher((path, options) => {
    const method = options?.method ?? 'GET';
    if (method === 'GET' && path === '/api/v1/series/7') return series;
    if (method === 'GET' && path === '/api/v1/series/7/collections') return { records: [] };
    if (method === 'GET' && path.startsWith('/api/v1/issues?seriesId=7')) {
      return pageOf(mockIssues);
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  }).fetcher;
  return renderWithProviders(
    <Routes>
      <Route path="/series/:id" element={<SeriesDetail />} />
    </Routes>,
    { fetcher, route: '/series/7' },
  );
}

describe('FRG-UI-022: series-detail collected-edition badge', () => {
  it('FRG-UI-022 — a typed series shows a book-type badge on the hero', async () => {
    renderDetailWithBooktype('tpb');

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    const badge = screen.getByTestId('booktype-badge');
    expect(badge).toHaveTextContent('TPB');
    expect(badge).toHaveAttribute('aria-label', 'Collected edition: Trade paperback');
  });

  it('FRG-UI-022 — a null-typed single-issues run shows no badge on the hero', async () => {
    renderDetailWithBooktype(null);

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Invincible' })).toBeInTheDocument(),
    );
    expect(screen.queryByTestId('booktype-badge')).toBeNull();
  });
});
