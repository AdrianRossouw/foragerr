import { describe, it, expect } from 'vitest';
import type { ReactElement } from 'react';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../test/renderWithProviders';
import { fakeFetcher } from '../test/fakeFetcher';
import { makeHealthComponent, mockHealthyComponents } from '../test/mockData';
import type { ComicVineBudgetBucket, SystemHealthComponent } from '../api/types';
import {
  ComicVineBudgetChip,
  ComicVineBudgetMeter,
  comicVineBudget,
  hotBuckets,
} from './ComicVineBudget';

/**
 * FRG-UI-040 / FRG-API-025 — the ComicVine budget meter. Both surfaces render
 * from the structured `detail` on the polled system-health component; there is
 * no budget endpoint. The full meter (Settings → General) always says
 * something; the compact chip (Sources review bar) says nothing until a bucket
 * is at or above the warning fraction.
 */

function bucket(
  overrides: Partial<ComicVineBudgetBucket> &
    Pick<ComicVineBudgetBucket, 'bucket' | 'used'>,
): ComicVineBudgetBucket {
  return {
    ceiling: 150,
    batch_used: 105,
    batch_ceiling: 105,
    resume_seconds: 0,
    ...overrides,
  };
}

function healthWithBuckets(
  buckets: ComicVineBudgetBucket[],
  flags: { degraded?: boolean; exhausted?: boolean } = {},
): SystemHealthComponent[] {
  return [
    makeHealthComponent({
      component: 'comicvine',
      label: 'ComicVine',
      state: buckets.length ? 'degraded' : 'ok',
      message: buckets.length ? 'ComicVine budget is approaching its ceiling' : null,
      detail: {
        buckets,
        degraded: flags.degraded ?? false,
        exhausted: flags.exhausted ?? false,
      },
    }),
    ...mockHealthyComponents.filter((c) => c.component !== 'comicvine'),
  ];
}

function renderWithHealth(ui: ReactElement, components: SystemHealthComponent[]) {
  const { fetcher } = fakeFetcher((path) => {
    if (path === '/api/v1/system/health') return components;
    throw new Error(`unexpected request: ${path}`);
  });
  return renderWithProviders(ui, { fetcher });
}

describe('FRG-UI-040: ComicVine budget meter', () => {
  it('FRG-UI-040 — the Settings meter renders each bucket with usage, batch share and resume time', async () => {
    renderWithHealth(
      <ComicVineBudgetMeter />,
      healthWithBuckets(
        [
          bucket({ bucket: 'issue', used: 150, resume_seconds: 720 }),
          bucket({ bucket: 'volumes', used: 121, batch_used: 60 }),
        ],
        { exhausted: true },
      ),
    );

    const issue = await screen.findByTestId('cv-budget-bucket-issue');
    expect(issue).toHaveTextContent('150 / 150');
    // The lane split is the whole point of the reserve: show what background
    // work has spent, and say when it has stopped.
    expect(issue).toHaveTextContent('background 105 / 105');
    expect(issue).toHaveTextContent('paused, interactive reserve remains');
    // A resume countdown appears only once capacity is actually gone.
    expect(issue).toHaveTextContent('resumes in ~12 min');

    const volumes = screen.getByTestId('cv-budget-bucket-volumes');
    expect(volumes).toHaveTextContent('121 / 150');
    expect(volumes).toHaveTextContent('background 60 / 105');
    expect(volumes).not.toHaveTextContent('paused');
    expect(volumes).not.toHaveTextContent('resumes in');

    // The exhausted state is explained, not just coloured.
    expect(screen.getByText(/deferred until the rolling hour clears/)).toBeInTheDocument();
  });

  it('FRG-UI-040 — the Settings meter says so plainly when nothing is under pressure', async () => {
    renderWithHealth(<ComicVineBudgetMeter />, mockHealthyComponents);

    expect(await screen.findByTestId('cv-budget-quiet')).toBeInTheDocument();
    expect(screen.queryByRole('meter')).not.toBeInTheDocument();
  });

  it('FRG-UI-040 — the review-bar chip is silent below the warning fraction', async () => {
    // 105/150 = 70%: the backend reports it (the batch lane has paused) but the
    // ceiling itself is not in question, so the review screen stays quiet.
    // The meter renders alongside purely as proof the health query RESOLVED —
    // otherwise "no chip" would pass on an unloaded query and prove nothing.
    renderWithHealth(
      <>
        <ComicVineBudgetChip />
        <ComicVineBudgetMeter />
      </>,
      healthWithBuckets([bucket({ bucket: 'issue', used: 105 })]),
    );

    await screen.findByTestId('cv-budget-bucket-issue');
    expect(screen.queryByTestId('cv-budget-chip')).not.toBeInTheDocument();
  });

  it('FRG-UI-040 — the review-bar chip appears with bucket and usage once a bucket is hot', async () => {
    renderWithHealth(
      <ComicVineBudgetChip />,
      healthWithBuckets([
        bucket({ bucket: 'issue', used: 145, resume_seconds: 0 }),
        bucket({ bucket: 'volumes', used: 130 }),
      ]),
    );

    const chip = await screen.findByTestId('cv-budget-chip');
    expect(chip).toHaveTextContent('ComicVine issue 145/150');
    expect(chip).toHaveTextContent('+1'); // a second hot bucket is counted
  });

  it('FRG-API-025 — the detail is read off the comicvine component only, and only when populated', () => {
    const withBuckets = healthWithBuckets([bucket({ bucket: 'issue', used: 140 })]);
    expect(comicVineBudget(withBuckets)?.buckets).toHaveLength(1);

    // Absent detail, an empty bucket list, and a missing payload are all the
    // same "nothing to say" answer — the UI has one quiet case, not three.
    expect(comicVineBudget(mockHealthyComponents)).toBeNull();
    expect(comicVineBudget(healthWithBuckets([]))).toBeNull();
    expect(comicVineBudget(undefined)).toBeNull();

    // The threshold is applied to usage against the ceiling, not to whatever
    // the backend chose to report.
    expect(hotBuckets(comicVineBudget(withBuckets))).toHaveLength(1);
    expect(
      hotBuckets(comicVineBudget(healthWithBuckets([bucket({ bucket: 'issue', used: 119 })]))),
    ).toHaveLength(0);
  });
});
