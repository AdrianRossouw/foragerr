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
import type { SeriesResource, StoreSourceResource } from '../api/types';
import type { Fetcher } from '../api/fetcher';
import { Sidebar } from './Sidebar';

function makeSource(
  overrides: Partial<StoreSourceResource> & Pick<StoreSourceResource, 'id'>,
): StoreSourceResource {
  return {
    type: 'humble',
    name: 'Humble Bundle',
    connection_state: 'connected',
    auto_sync: false,
    last_sync_status: 'ok',
    settings: {},
    ...overrides,
  };
}

/** A fetcher answering exactly the sidebar's read paths. */
function sidebarFetcher(opts: {
  series: SeriesResource[];
  queueTotal: number;
  version?: string;
  warnings?: unknown[];
  sources?: StoreSourceResource[];
  newPerSource?: Record<number, number>;
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
    // Source entitlement new-count slice: /api/v1/sources/{id}/entitlements?review_status=new
    const ent = path.match(/\/api\/v1\/sources\/(\d+)\/entitlements/);
    if (ent) {
      const n = opts.newPerSource?.[Number(ent[1])] ?? 0;
      return Array.from({ length: n }, (_, i) => ({ id: i + 1 }));
    }
    if (path === '/api/v1/sources') return opts.sources ?? [];
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
 * the single active-work count badge (Queue = tracked-download count). Comics,
 * Wanted, and Sources-new counts are NOT badged (wanted-count-consistency).
 */
describe('FRG-UI-023: sidebar nav lists only shipped screens', () => {
  it('FRG-UI-023 — every nav entry routes to an implemented route; Calendar + Creators shipped', () => {
    renderWithProviders(<Sidebar />, {
      withRouter: true,
      fetcher: sidebarFetcher({ series: [], queueTotal: 0 }),
      client: createQueryClient(),
    });

    const shipped = [
      '/',
      '/creators',
      '/calendar',
      '/add',
      '/library-import',
      '/wanted',
      '/sources',
      '/queue',
      '/history',
      '/blocklist',
      '/settings/general',
      '/settings/media-management',
      '/settings/indexers',
      '/settings/download-clients',
      '/settings/security',
      '/system/status',
      '/system/health',
      '/system/tasks',
      '/system/logs',
    ];
    const hrefs = screen
      .getAllByRole('link')
      .map((a) => a.getAttribute('href'));
    for (const href of hrefs) expect(shipped).toContain(href);

    // Calendar shipped in m4-pull-experience (FRG-UI-018).
    expect(screen.getByRole('link', { name: /calendar/i })).toHaveAttribute(
      'href',
      '/calendar',
    );
    // Creators ships in m5-creators-screens (FRG-UI-027): now present, routing
    // to /creators, and ordered right after Comics (before Calendar).
    expect(screen.getByRole('link', { name: /creators/i })).toHaveAttribute(
      'href',
      '/creators',
    );
    const labels = screen.getAllByRole('link').map((a) => a.textContent);
    expect(labels.indexOf('Creators')).toBe(labels.indexOf('Comics') + 1);
    expect(labels.indexOf('Creators')).toBeLessThan(labels.indexOf('Calendar'));
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
  it('FRG-UI-023 — only the Queue active-work badge renders; Comics and Wanted carry no count badge', async () => {
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
      expect(screen.getByTestId('nav-badge-queue')).toHaveTextContent('4'),
    );
    // Library size and missing counts are NOT badged on the nav — they read
    // differently against their screens (wanted-count-consistency). Only
    // active work (the queue) is badged.
    expect(screen.queryByTestId('nav-badge-series')).toBeNull();
    expect(screen.queryByTestId('nav-badge-wanted')).toBeNull();

    // Footer surfaces the running version + health state.
    await waitFor(() =>
      expect(screen.getByTestId('sidebar-status')).toHaveTextContent(
        'Foragerr 1.4.2 — all healthy',
      ),
    );
  });

  it('FRG-UI-023 — the queue badge updates without reload when its cache changes', async () => {
    const client = createQueryClient();
    renderWithProviders(<Sidebar />, {
      withRouter: true,
      client,
      fetcher: sidebarFetcher({ series: [], queueTotal: 2 }),
    });

    await waitFor(() =>
      expect(screen.getByTestId('nav-badge-queue')).toHaveTextContent('2'),
    );

    // A WS-driven cache write (the same mechanism the WebSocketBridge uses)
    // changes the queue count; the badge re-renders with no page reload.
    act(() => {
      client.setQueryData(queryKeys.queue.count(), 5);
    });
    await waitFor(() =>
      expect(screen.getByTestId('nav-badge-queue')).toHaveTextContent('5'),
    );
  });

  it('FRG-UI-029 — a connected source with unreviewed-new items shows no nav count badge', async () => {
    renderWithProviders(<Sidebar />, {
      withRouter: true,
      client: createQueryClient(),
      fetcher: sidebarFetcher({
        series: [],
        queueTotal: 0,
        sources: [makeSource({ id: 5, connection_state: 'connected' })],
        newPerSource: { 5: 7 },
      }),
    });

    expect(screen.getByRole('link', { name: /Sources/ })).toHaveAttribute(
      'href',
      '/sources',
    );
    // Unreviewed-new is not badged on the nav (its comic/non-comic scope is
    // only clear on the page); with no expiry, the Sources item has no badge.
    await waitFor(() =>
      expect(screen.queryByTestId('nav-badge-sources')).toBeNull(),
    );
  });

  it('FRG-UI-029 — an expired source flips the Sources badge to an amber "!" and the footer to attention', async () => {
    renderWithProviders(<Sidebar />, {
      withRouter: true,
      client: createQueryClient(),
      fetcher: sidebarFetcher({
        series: [],
        queueTotal: 0,
        version: '1.4.2',
        sources: [makeSource({ id: 9, connection_state: 'expired' })],
      }),
    });

    const badge = await screen.findByTestId('nav-badge-sources');
    expect(badge).toHaveTextContent('!');
    expect(badge.className).toMatch(/navBadgeWarn/);
    await waitFor(() =>
      expect(screen.getByTestId('sidebar-status')).toHaveTextContent(
        'sync needs attention',
      ),
    );
  });

  it('FRG-UI-029 — no source configured shows no Sources badge', async () => {
    renderWithProviders(<Sidebar />, {
      withRouter: true,
      client: createQueryClient(),
      fetcher: sidebarFetcher({ series: [], queueTotal: 0, sources: [] }),
    });
    // The nav item is present…
    expect(screen.getByRole('link', { name: /Sources/ })).toBeInTheDocument();
    // …but a clean, source-less install carries no badge.
    await waitFor(() =>
      expect(screen.queryByTestId('nav-badge-sources')).toBeNull(),
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
