import { describe, it, expect, vi } from 'vitest';
import { screen, act, fireEvent, within } from '@testing-library/react';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import {
  makeHealthComponent,
  makeHealthWarning,
  mockHealthyComponents,
} from '../../test/mockData';
import { HEALTH_POLL_INTERVAL_MS } from '../../api/hooks';
import { ApiRequestError } from '../../api/fetcher';
import { HealthScreen } from './HealthScreen';

/**
 * FRG-UI-016 / FRG-NFR-011 — System: Health screen. Renders GET
 * /api/v1/health (warnings + remediation hints) and GET
 * /api/v1/system/health (per-component table: ok / degraded with
 * disabled-until / error). Both queries poll, so a recovered component
 * clears on the next poll with no manual refresh or restart.
 */

const oneHourFromNow = new Date(Date.now() + 60 * 60 * 1000).toISOString();

const degradedIndexer = makeHealthComponent({
  component: 'indexer:3',
  label: 'Indexer: DogNZB',
  state: 'degraded',
  last_failure: '2026-07-06T10:00:00Z',
  disabled_until: oneHourFromNow,
});

describe('FRG-UI-016: system health screen', () => {
  it('FRG-UI-016 — Health screen shows warnings with remediation and per-component state', async () => {
    const warnings = [
      makeHealthWarning({
        source: 'indexer:3',
        type: 'warning',
        message: 'DogNZB is disabled after repeated failures.',
        remediationHint: 'Check the indexer credentials and try again.',
      }),
    ];
    const components = [
      ...mockHealthyComponents.filter((c) => c.component !== 'indexer:3'),
      degradedIndexer,
    ];
    const { fetcher } = fakeFetcher((path) => {
      if (path === '/api/v1/health') return warnings;
      if (path === '/api/v1/system/health') return components;
      throw new Error(`unexpected request: ${path}`);
    });
    renderWithProviders(<HealthScreen />, { fetcher });

    const warningRow = await screen.findByTestId('health-warning-indexer:3');
    expect(within(warningRow).getByText('DogNZB is disabled after repeated failures.')).toBeInTheDocument();
    expect(
      within(warningRow).getByText('Check the indexer credentials and try again.'),
    ).toBeInTheDocument();

    const componentRow = screen.getByTestId('health-component-indexer:3');
    // The human-readable label is the primary name shown to the user; the
    // machine id stays visible too (secondary), but must not be the only
    // thing rendered (FRG-UI-016 — no raw machine ids as the primary name).
    expect(within(componentRow).getByText('Indexer: DogNZB')).toBeInTheDocument();
    expect(within(componentRow).getByText('indexer:3')).toBeInTheDocument();
    expect(within(componentRow).getByText('Degraded')).toBeInTheDocument();
    // A disabled-until countdown is rendered ("in Xm"/"in Xh Ym"), not a dash.
    const cells = within(componentRow).getAllByRole('cell');
    expect(cells[cells.length - 1].textContent).toMatch(/^in /);
  });

  it('FRG-UI-016 — a healthy system Health screen is explicitly clear', async () => {
    const { fetcher } = fakeFetcher((path) => {
      if (path === '/api/v1/health') return [];
      if (path === '/api/v1/system/health') return mockHealthyComponents;
      throw new Error(`unexpected request: ${path}`);
    });
    renderWithProviders(<HealthScreen />, { fetcher });

    await screen.findByTestId('health-all-healthy');
    expect(screen.queryByTestId('health-warnings')).not.toBeInTheDocument();
    for (const component of mockHealthyComponents) {
      expect(
        within(screen.getByTestId(`health-component-${component.component}`)).getByText(
          'OK',
        ),
      ).toBeInTheDocument();
    }
  });

  it('FRG-UI-016 — a recovered component clears its warning on the next poll, without a manual refresh or restart', async () => {
    let recovered = false;
    const { fetcher } = fakeFetcher((path) => {
      if (path === '/api/v1/health') {
        return recovered
          ? []
          : [
              makeHealthWarning({
                source: 'indexer:3',
                remediationHint: 'Check the indexer credentials and try again.',
              }),
            ];
      }
      if (path === '/api/v1/system/health') {
        return recovered
          ? mockHealthyComponents
          : [
              ...mockHealthyComponents.filter((c) => c.component !== 'indexer:3'),
              degradedIndexer,
            ];
      }
      throw new Error(`unexpected request: ${path}`);
    });

    // Fake timers must be installed BEFORE mount: React Query registers its
    // refetchInterval timer against whichever setTimeout is global at mount
    // time, so faking the clock only after the initial fetch would leave a
    // REAL timer running that advanceTimersByTimeAsync can never trigger.
    vi.useFakeTimers();
    try {
      renderWithProviders(<HealthScreen />, { fetcher });
      // Flush the initial (promise-based, not timer-based) fetch.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByTestId('health-warning-indexer:3')).toBeInTheDocument();

      recovered = true;
      // Advance past two poll intervals so both independently-scheduled
      // queries (warnings + per-component) are guaranteed to have refetched.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(HEALTH_POLL_INTERVAL_MS * 2);
      });
    } finally {
      vi.useRealTimers();
    }

    expect(screen.getByTestId('health-all-healthy')).toBeInTheDocument();
    expect(screen.queryByTestId('health-warning-indexer:3')).not.toBeInTheDocument();
  });

  it('FRG-UI-016 — a sustained poll failure keeps the stale table rendered with a dismissable banner, not a blank error state', async () => {
    let shouldFail = false;
    const { fetcher } = fakeFetcher((path) => {
      if (shouldFail) throw new ApiRequestError(500, null, path);
      if (path === '/api/v1/health') return [];
      if (path === '/api/v1/system/health') return mockHealthyComponents;
      throw new Error(`unexpected request: ${path}`);
    });

    vi.useFakeTimers();
    try {
      renderWithProviders(<HealthScreen />, { fetcher });
      // Flush the initial (promise-based) fetch — both queries succeed once.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByTestId('health-all-healthy')).toBeInTheDocument();

      shouldFail = true;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(HEALTH_POLL_INTERVAL_MS * 2);
      });
    } finally {
      vi.useRealTimers();
    }

    // The retained (stale) data stays up — NOT the blank "Could not load"
    // state, since there is data to show.
    expect(screen.queryByTestId('health-all-healthy')).toBeInTheDocument();
    expect(
      screen.queryByText('Could not load system health.'),
    ).not.toBeInTheDocument();

    const banner = screen.getByTestId('health-stale-banner');
    expect(banner).toHaveTextContent(/stale/i);
    expect(banner).toHaveTextContent(/last update failed/i);

    fireEvent.click(within(banner).getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByTestId('health-stale-banner')).not.toBeInTheDocument();
    // Dismissing the banner must not also hide the still-valid stale data.
    expect(screen.getByTestId('health-all-healthy')).toBeInTheDocument();
  });

  it('FRG-UI-038 — the components table sits in a keyboard-focusable, labelled scroll region', async () => {
    const { fetcher } = fakeFetcher((path) => {
      if (path === '/api/v1/health') return [];
      if (path === '/api/v1/system/health') return mockHealthyComponents;
      throw new Error(`unexpected request: ${path}`);
    });
    renderWithProviders(<HealthScreen />, { fetcher });

    // The wide component table overflows horizontally; its scroll container
    // must be keyboard-reachable (axe scrollable-region-focusable) — a labelled
    // region with tabindex=0 rather than a mouse-only overflow div.
    const region = await screen.findByTestId('health-components-scroll');
    expect(region).toHaveAttribute('tabindex', '0');
    expect(region).toHaveAttribute('role', 'region');
    expect(region).toHaveAccessibleName('Health components');
    // The table it wraps is still rendered inside it.
    expect(within(region).getByRole('table')).toBeInTheDocument();
  });

  it('FRG-UI-016 / FRG-API-014 — Last Success / Last Failure render formatted dates, not raw ISO strings', async () => {
    const components = [
      makeHealthComponent({
        component: 'database',
        label: 'Database',
        // Deliberately one offset-less (real wire shape) and one Z-suffixed
        // timestamp — both must render as the same formatted date, never
        // the raw ISO string.
        last_success: '2026-07-06T12:00:00',
        last_failure: '2026-07-05T09:00:00Z',
      }),
    ];
    const { fetcher } = fakeFetcher((path) => {
      if (path === '/api/v1/health') return [];
      if (path === '/api/v1/system/health') return components;
      throw new Error(`unexpected request: ${path}`);
    });
    renderWithProviders(<HealthScreen />, { fetcher });

    const row = await screen.findByTestId('health-component-database');
    expect(within(row).getByText('Jul 6, 2026')).toBeInTheDocument();
    expect(within(row).getByText('Jul 5, 2026')).toBeInTheDocument();
    expect(
      within(row).queryByText('2026-07-06T12:00:00'),
    ).not.toBeInTheDocument();
    expect(
      within(row).queryByText('2026-07-05T09:00:00Z'),
    ).not.toBeInTheDocument();
  });
});
