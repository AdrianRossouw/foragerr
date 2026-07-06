import { describe, it, expect, vi } from 'vitest';
import { screen, act, within } from '@testing-library/react';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import {
  makeHealthComponent,
  makeHealthWarning,
  mockHealthyComponents,
} from '../../test/mockData';
import { HEALTH_POLL_INTERVAL_MS } from '../../api/hooks';
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
  component: 'indexer:DogNZB',
  state: 'degraded',
  last_failure: '2026-07-06T10:00:00Z',
  disabled_until: oneHourFromNow,
});

describe('FRG-UI-016: system health screen', () => {
  it('FRG-UI-016 — Health screen shows warnings with remediation and per-component state', async () => {
    const warnings = [
      makeHealthWarning({
        source: 'indexer:DogNZB',
        type: 'warning',
        message: 'DogNZB is disabled after repeated failures.',
        remediationHint: 'Check the indexer credentials and try again.',
      }),
    ];
    const components = [
      ...mockHealthyComponents.filter((c) => c.component !== 'indexer:DogNZB'),
      degradedIndexer,
    ];
    const { fetcher } = fakeFetcher((path) => {
      if (path === '/api/v1/health') return warnings;
      if (path === '/api/v1/system/health') return components;
      throw new Error(`unexpected request: ${path}`);
    });
    renderWithProviders(<HealthScreen />, { fetcher });

    const warningRow = await screen.findByTestId('health-warning-indexer:DogNZB');
    expect(within(warningRow).getByText('DogNZB is disabled after repeated failures.')).toBeInTheDocument();
    expect(
      within(warningRow).getByText('Check the indexer credentials and try again.'),
    ).toBeInTheDocument();

    const componentRow = screen.getByTestId('health-component-indexer:DogNZB');
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
                source: 'indexer:DogNZB',
                remediationHint: 'Check the indexer credentials and try again.',
              }),
            ];
      }
      if (path === '/api/v1/system/health') {
        return recovered
          ? mockHealthyComponents
          : [
              ...mockHealthyComponents.filter((c) => c.component !== 'indexer:DogNZB'),
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
      expect(screen.getByTestId('health-warning-indexer:DogNZB')).toBeInTheDocument();

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
    expect(screen.queryByTestId('health-warning-indexer:DogNZB')).not.toBeInTheDocument();
  });
});
