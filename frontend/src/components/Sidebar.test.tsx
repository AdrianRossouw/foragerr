import { describe, it, expect, beforeEach } from 'vitest';
import { screen, within, waitFor, act } from '@testing-library/react';
import { renderWithProviders } from '../test/renderWithProviders';
import { createQueryClient } from '../queryClient';
import { queryKeys } from '../api/queryKeys';
import { useConnectionStore } from '../ws/connectionStore';
import {
  makeSeriesResource,
  makeSystemStatus,
  mockQueueEnvelope,
} from '../test/mockData';
import type { SeriesResource } from '../api/types';
import type { Fetcher } from '../api/fetcher';
import { Sidebar } from './Sidebar';

/** A fetcher answering exactly the sidebar's four read paths. */
function sidebarFetcher(opts: {
  series: SeriesResource[];
  queueTotal: number;
  version?: string;
  warnings?: unknown[];
}): Fetcher {
  const resolve = async (path: string): Promise<unknown> => {
    if (path.includes('/api/v1/series?')) {
      return {
        page: 1,
        pageSize: 200,
        sortKey: 'sort_title',
        sortDirection: 'asc',
        totalRecords: opts.series.length,
        records: opts.series,
      };
    }
    if (path.includes('/api/v1/queue')) {
      const env = mockQueueEnvelope([]);
      return { ...env, totalRecords: opts.queueTotal };
    }
    if (path === '/api/v1/health') return opts.warnings ?? [];
    if (path.includes('/api/v1/system/status')) {
      return makeSystemStatus({ version: opts.version ?? '9.9.9' });
    }
    throw new Error(`unexpected path ${path}`);
  };
  return resolve as unknown as Fetcher;
}

function withMissing(id: number, missing: number): SeriesResource {
  const s = makeSeriesResource({ id });
  return { ...s, statistics: { ...s.statistics, missing_count: missing } };
}

// The connection store is a module-level singleton; reset it to a connected
// baseline before each test so footer-text assertions are not order-dependent.
beforeEach(() => {
  useConnectionStore.setState({ status: 'connected' });
});

/**
 * FRG-UI-016 — nav reachability: the System area (Status / Health / Tasks)
 * is reachable from the sidebar as its own group, alongside the existing
 * Settings/Activity groups (Sonarr-shaped nav).
 */
describe('FRG-UI-016: System nav group', () => {
  it('FRG-UI-016 — the sidebar exposes a System group linking to Status, Health, and Tasks', () => {
    renderWithProviders(<Sidebar />, { withRouter: true });

    const group = screen.getByText('System').closest('nav');
    expect(group).not.toBeNull();

    expect(
      within(group as HTMLElement).getByRole('link', { name: 'Status' }),
    ).toHaveAttribute('href', '/system/status');
    expect(
      within(group as HTMLElement).getByRole('link', { name: 'Health' }),
    ).toHaveAttribute('href', '/system/health');
    expect(
      within(group as HTMLElement).getByRole('link', { name: 'Tasks' }),
    ).toHaveAttribute('href', '/system/tasks');
  });
});

/**
 * FRG-UI-020 — nav reachability: Settings -> General (the ComicVine
 * credential settings screen) is reachable from the sidebar, ahead of the
 * existing Media Management/Indexers/Download Clients settings items.
 */
describe('FRG-UI-020: Settings nav group', () => {
  it('FRG-UI-020 — the sidebar exposes a General settings item routing to /settings/general', () => {
    renderWithProviders(<Sidebar />, { withRouter: true });

    const group = screen.getByText('Settings').closest('nav');
    expect(group).not.toBeNull();

    expect(
      within(group as HTMLElement).getByRole('link', { name: 'General' }),
    ).toHaveAttribute('href', '/settings/general');
  });
});

/**
 * FRG-UI-023 — the application shell's sidebar: shipped-screens-only nav and
 * live count badges (Comics = library series count, Queue = tracked-download
 * count, Wanted = series-with-missing-issues in warn style).
 */
describe('FRG-UI-023: sidebar nav lists only shipped screens', () => {
  it('FRG-UI-023 — every nav entry routes to an implemented route; no Calendar/Creators', () => {
    renderWithProviders(<Sidebar />, {
      withRouter: true,
      fetcher: sidebarFetcher({ series: [], queueTotal: 0 }),
      client: createQueryClient(),
    });

    const shipped = [
      '/',
      '/add',
      '/library-import',
      '/wanted',
      '/queue',
      '/history',
      '/blocklist',
      '/settings/general',
      '/settings/media-management',
      '/settings/indexers',
      '/settings/download-clients',
      '/system/status',
      '/system/health',
      '/system/tasks',
      '/system/logs',
    ];
    const hrefs = screen
      .getAllByRole('link')
      .map((a) => a.getAttribute('href'));
    for (const href of hrefs) expect(shipped).toContain(href);

    // Future screens are absent until their change ships them.
    expect(screen.queryByRole('link', { name: /calendar/i })).toBeNull();
    expect(screen.queryByRole('link', { name: /creators?/i })).toBeNull();
  });
});

describe('FRG-UI-023: logo lockup', () => {
  it('FRG-UI-023 — the header lockup renders the inline SVG brand mark, not a font glyph', () => {
    const { container } = renderWithProviders(<Sidebar />, {
      withRouter: true,
      fetcher: sidebarFetcher({ series: [], queueTotal: 0 }),
      client: createQueryClient(),
    });

    // The handoff's mark is pure SVG (ant + hexagon knocked out on the tile);
    // a regression back to an icon-font placeholder would render an <i> here.
    // The lockup is also the home link (owner request 2026-07-10).
    const brand = container.querySelector('aside > a');
    expect(brand?.getAttribute('href')).toBe('/');
    expect(brand?.querySelector('svg')).not.toBeNull();
    expect(brand?.querySelector('i[class*="fa-"]')).toBeNull();
    expect(brand?.textContent).toBe('Foragerr');
  });
});

describe('FRG-UI-023: sidebar count badges are live', () => {
  it('FRG-UI-023 — Comics/Queue/Wanted badges reflect the caches, Wanted uses warn style', async () => {
    renderWithProviders(<Sidebar />, {
      withRouter: true,
      client: createQueryClient(),
      fetcher: sidebarFetcher({
        series: [withMissing(1, 3), withMissing(2, 0), withMissing(3, 5)],
        queueTotal: 4,
        version: '1.4.2',
      }),
    });

    await waitFor(() =>
      expect(screen.getByTestId('nav-badge-series')).toHaveTextContent('3'),
    );
    expect(screen.getByTestId('nav-badge-queue')).toHaveTextContent('4');
    // Two of three series carry missing issues.
    const wanted = screen.getByTestId('nav-badge-wanted');
    expect(wanted).toHaveTextContent('2');
    expect(wanted.className).toMatch(/navBadgeWarn/);

    // Footer surfaces the running version + health state.
    await waitFor(() =>
      expect(screen.getByTestId('sidebar-status')).toHaveTextContent(
        'Foragerr 1.4.2 — all healthy',
      ),
    );
  });

  it('FRG-UI-023 — a badge updates without reload when its cache changes', async () => {
    const client = createQueryClient();
    renderWithProviders(<Sidebar />, {
      withRouter: true,
      client,
      fetcher: sidebarFetcher({ series: [withMissing(1, 1)], queueTotal: 0 }),
    });

    await waitFor(() =>
      expect(screen.getByTestId('nav-badge-series')).toHaveTextContent('1'),
    );

    // A WS-driven cache write (the same mechanism the WebSocketBridge uses)
    // grows the library; the badge re-renders with no page reload.
    act(() => {
      client.setQueryData(queryKeys.series.all(), [
        withMissing(1, 1),
        withMissing(2, 0),
      ]);
    });
    await waitFor(() =>
      expect(screen.getByTestId('nav-badge-series')).toHaveTextContent('2'),
    );
  });

  it('FRG-UI-023 — a dropped socket surfaces as reconnecting even when health is clean', async () => {
    act(() => {
      useConnectionStore.setState({ status: 'disconnected' });
    });
    renderWithProviders(<Sidebar />, {
      withRouter: true,
      client: createQueryClient(),
      // Healthy cache (no warnings) — the visible text must still reflect the
      // dropped connection rather than claiming "all healthy".
      fetcher: sidebarFetcher({ series: [], queueTotal: 0, version: '1.4.2' }),
    });

    const footer = screen.getByTestId('sidebar-status');
    await waitFor(() => expect(footer).toHaveTextContent('reconnecting…'));
    expect(footer).not.toHaveTextContent('all healthy');
    // The row is an assertive-but-polite live region for screen readers.
    expect(footer).toHaveAttribute('role', 'status');
    expect(footer).toHaveAttribute('aria-live', 'polite');
    // The connection dot still reflects the disconnected state.
    expect(screen.getByTestId('connection-status')).toHaveAttribute(
      'data-status',
      'disconnected',
    );
  });
});
