import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { mockReleases } from '../../test/mockData';
import { ApiRequestError, type Fetcher, type FetcherInit } from '../../api/fetcher';
import type { ReleaseDecision } from '../../api/types';
import { InteractiveSearchOverlay } from './InteractiveSearchOverlay';

const EXPIRED_MESSAGE =
  'release is no longer cached; run the interactive search again before grabbing';

/**
 * FRG-UI-007 — Interactive search overlay: every decision from GET /release
 * renders in the endpoint's (comparator) order, rejection reasons appear
 * verbatim, grabs POST the (indexer_id, guid) cache key, and an expired cache
 * entry surfaces the backend's deterministic "search again" message.
 */
describe('FRG-UI-007: interactive search overlay', () => {
  it('FRG-UI-007 — lists approved AND rejected decisions with indexer, size, age, and score, in response order', async () => {
    const { spy, fetcher } = fakeFetcher(() => mockReleases);
    renderWithProviders(
      <InteractiveSearchOverlay issueId={42} contextTitle="Saga #41" onClose={() => {}} />,
      { fetcher },
    );

    await screen.findByTestId('release-row-guid-approved-best');
    expect(spy).toHaveBeenCalledWith('/api/v1/release?issueId=42');

    // Every decision is a row — approved and rejected alike.
    const rows = screen.getAllByTestId(/^release-row-/);
    expect(rows).toHaveLength(mockReleases.length);
    // Rendered in EXACTLY the order the endpoint returned (comparator order).
    expect(rows.map((r) => r.getAttribute('data-testid'))).toEqual([
      'release-row-guid-approved-best',
      'release-row-guid-approved-second',
      'release-row-guid-rejected',
    ]);

    // Column content for one approved and the rejected row.
    const best = within(rows[0]);
    expect(best.getByText('DogNZB')).toBeInTheDocument(); // indexer
    expect(best.getByText('40.1 MB')).toBeInTheDocument(); // size
    expect(best.getByText('3d')).toBeInTheDocument(); // age
    expect(best.getByText('120')).toBeInTheDocument(); // score
    expect(best.getByText('cbz')).toBeInTheDocument(); // format

    const rejected = within(rows[2]);
    expect(rejected.getByText('Saga 041 scanned')).toBeInTheDocument();
    expect(rejected.getByText('-5')).toBeInTheDocument();
  });

  it('FRG-UI-007 — rejection reasons render verbatim, one per reason', async () => {
    const { fetcher } = fakeFetcher(() => mockReleases);
    const user = userEvent.setup();
    renderWithProviders(
      <InteractiveSearchOverlay issueId={42} onClose={() => {}} />,
      { fetcher },
    );

    const row = await screen.findByTestId('release-row-guid-rejected');
    await user.click(
      within(row).getByRole('button', { name: 'Rejected — show reasons' }),
    );

    const popover = screen.getByRole('dialog', { name: 'Rejected — show reasons' });
    const items = within(popover).getAllByRole('listitem');
    // One list item per reason, wording untouched.
    expect(items.map((li) => li.textContent)).toEqual([
      'Below minimum size',
      'Release too old',
    ]);
  });

  it('FRG-UI-007 — grab POSTs the (indexer_id, guid) cache key and only approved rows expose a grab button', async () => {
    const { spy, fetcher } = fakeFetcher((_path, init) =>
      init?.method === 'POST' ? { id: 1, name: 'grab-release' } : mockReleases,
    );
    const user = userEvent.setup();
    renderWithProviders(
      <InteractiveSearchOverlay issueId={42} onClose={() => {}} />,
      { fetcher },
    );

    const rejectedRow = await screen.findByTestId('release-row-guid-rejected');
    // A rejected row never exposes the plain one-click Grab — its override
    // (FRG-UI-044) is the distinct, confirm-gated "Grab anyway".
    expect(
      within(rejectedRow).queryByRole('button', { name: 'Grab Saga 041 scanned' }),
    ).toBeNull();
    expect(
      within(rejectedRow).getByRole('button', { name: 'Grab Saga 041 scanned anyway' }),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole('button', { name: 'Grab Saga 041 (2017) (Digital)' }),
    );

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/release',
        expect.objectContaining({
          method: 'POST',
          body: { indexer_id: 3, guid: 'guid-approved-best' },
        }),
      ),
    );
    // The grabbed row's button is replaced by a grabbed marker.
    const row = screen.getByTestId('release-row-guid-approved-best');
    await waitFor(() => expect(within(row).getByText('Grabbed')).toBeInTheDocument());
  });

  it('FRG-UI-007 — an expired-cache grab surfaces the deterministic search-again error distinctly', async () => {
    const fetcher = vi.fn(async (_path: string, init?: FetcherInit) => {
      if (init?.method === 'POST') {
        throw new ApiRequestError(404, { message: EXPIRED_MESSAGE, errors: [] }, '/api/v1/release');
      }
      return mockReleases;
    }) as unknown as Fetcher;
    const user = userEvent.setup();
    renderWithProviders(
      <InteractiveSearchOverlay issueId={42} onClose={() => {}} />,
      { fetcher },
    );

    await screen.findByTestId('release-row-guid-approved-best');
    await user.click(
      screen.getByRole('button', { name: 'Grab Saga 041 (2017) (Digital)' }),
    );

    // The expired-cache banner is DISTINCT from a generic failure banner and
    // carries the backend's message verbatim.
    const banner = await screen.findByTestId('grab-error-expired');
    expect(banner).toHaveTextContent(EXPIRED_MESSAGE);
    expect(screen.queryByTestId('grab-error')).toBeNull();
    // It offers the corrective action the message names.
    expect(
      within(banner).getByRole('button', { name: 'Search again' }),
    ).toBeInTheDocument();
  });

  it('FRG-UI-007 — a non-404 grab failure renders as a generic error, not the expired banner', async () => {
    const fetcher = vi.fn(async (_path: string, init?: FetcherInit) => {
      if (init?.method === 'POST') {
        throw new ApiRequestError(500, { message: 'boom', errors: [] }, '/api/v1/release');
      }
      return mockReleases;
    }) as unknown as Fetcher;
    const user = userEvent.setup();
    renderWithProviders(
      <InteractiveSearchOverlay issueId={42} onClose={() => {}} />,
      { fetcher },
    );

    await screen.findByTestId('release-row-guid-approved-best');
    await user.click(
      screen.getByRole('button', { name: 'Grab Saga 041 (2017) (Webrip)' }),
    );

    const banner = await screen.findByTestId('grab-error');
    expect(banner).toHaveTextContent('Grab failed: boom');
    expect(screen.queryByTestId('grab-error-expired')).toBeNull();
  });
});

/**
 * FRG-UI-041 — per-indexer outcomes beside the results: a partial result is
 * VISIBLY partial (the slow indexer named, with its budget), the all-searched
 * case stays quiet, and a response without the additive field renders no strip
 * at all rather than an empty or invented one.
 */
describe('FRG-UI-041: per-indexer search outcomes', () => {
  const enveloped = (indexers: unknown[], releases = mockReleases) => ({
    releases,
    indexers,
  });

  it('FRG-UI-041 — a timed-out indexer is named with its budget, the returned rows still render and grab', async () => {
    const { spy, fetcher } = fakeFetcher((_path, init) =>
      init?.method === 'POST'
        ? { id: 1, name: 'grab-release' }
        : enveloped([
            { indexer_id: 3, name: 'DogNZB', outcome: 'searched', budget_seconds: null },
            { indexer_id: 4, name: 'NZB.su', outcome: 'timed_out', budget_seconds: 20 },
          ]),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <InteractiveSearchOverlay issueId={42} onClose={() => {}} />,
      { fetcher },
    );

    const strip = await screen.findByTestId('indexer-outcomes');
    expect(strip).toHaveAttribute('data-state', 'partial');
    expect(strip).toHaveTextContent('Partial results');
    // The slow indexer is NAMED, with the budget it hit — never inferred.
    expect(screen.getByTestId('indexer-outcome-4')).toHaveTextContent(
      'NZB.su — timed out after 20s',
    );
    expect(screen.getByTestId('indexer-outcome-3')).toHaveTextContent(
      'DogNZB — searched',
    );

    // The rows that DID come back render and grab exactly as usual.
    expect(screen.getAllByTestId(/^release-row-/)).toHaveLength(mockReleases.length);
    await user.click(
      screen.getByRole('button', { name: 'Grab Saga 041 (2017) (Digital)' }),
    );
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/release',
        expect.objectContaining({
          method: 'POST',
          body: { indexer_id: 3, guid: 'guid-approved-best' },
        }),
      ),
    );
  });

  it('FRG-UI-041 — every indexer searched renders the quiet form with no warning chrome', async () => {
    const { fetcher } = fakeFetcher(() =>
      enveloped([
        { indexer_id: 3, name: 'DogNZB', outcome: 'searched', budget_seconds: null },
        { indexer_id: 4, name: 'NZB.su', outcome: 'searched', budget_seconds: null },
      ]),
    );
    renderWithProviders(
      <InteractiveSearchOverlay issueId={42} onClose={() => {}} />,
      { fetcher },
    );

    const strip = await screen.findByTestId('indexer-outcomes');
    expect(strip).toHaveAttribute('data-state', 'all-searched');
    expect(strip).toHaveTextContent('Searched 2 indexers: DogNZB, NZB.su');
    // Quiet: no alarm wording and no per-indexer warning entries.
    expect(strip.textContent).not.toMatch(/Partial|timed out|failed|backing off/);
    expect(screen.queryByTestId('indexer-outcome-3')).toBeNull();
  });

  it('FRG-UI-041 — failed and backing-off indexers are marked, including when nothing came back at all', async () => {
    const { fetcher } = fakeFetcher(() =>
      enveloped(
        [
          { indexer_id: 3, name: 'DogNZB', outcome: 'failed', budget_seconds: null },
          { indexer_id: 4, name: 'NZB.su', outcome: 'backing_off', budget_seconds: null },
        ],
        [],
      ),
    );
    renderWithProviders(
      <InteractiveSearchOverlay issueId={42} onClose={() => {}} />,
      { fetcher },
    );

    const strip = await screen.findByTestId('indexer-outcomes');
    expect(strip).toHaveAttribute('data-state', 'partial');
    expect(screen.getByTestId('indexer-outcome-3')).toHaveTextContent(
      'DogNZB — failed',
    );
    expect(screen.getByTestId('indexer-outcome-4')).toHaveTextContent(
      'NZB.su — backing off',
    );
    // "Nothing found" and "nobody answered" stay distinguishable.
    expect(
      screen.getByText('No results from any enabled indexer.'),
    ).toBeInTheDocument();
  });

  it('FRG-UI-041 — a response WITHOUT the additive outcomes field renders the rows and no strip', async () => {
    // The long-standing bare-array shape: an older or cached response.
    const { fetcher } = fakeFetcher(() => mockReleases);
    renderWithProviders(
      <InteractiveSearchOverlay issueId={42} onClose={() => {}} />,
      { fetcher },
    );

    await screen.findByTestId('release-row-guid-approved-best');
    expect(screen.getAllByTestId(/^release-row-/)).toHaveLength(mockReleases.length);
    expect(screen.queryByTestId('indexer-outcomes')).toBeNull();
  });
});

/**
 * FRG-UI-044 — force-grab: rejected AND temporarily-rejected releases offer a
 * distinct, confirm-gated "Grab anyway" that grabs with force:true, while
 * approved releases keep their plain one-click Grab with no confirm and no
 * force flag. Synthetic titles only.
 */
describe('FRG-UI-044: force-grab of rejected releases', () => {
  const allRejected: ReleaseDecision[] = [
    {
      indexer_id: 7,
      guid: 'r1',
      indexer_name: 'IndexerOne',
      title: 'Widget Chronicles 001',
      format: null,
      size_bytes: 1_000_000,
      age_seconds: 86_400,
      score: -3,
      outcome: 'rejected',
      approved: false,
      rejections: ['Below minimum size', 'Wrong format'],
    },
    {
      indexer_id: 7,
      guid: 'r2',
      indexer_name: 'IndexerOne',
      title: 'Widget Chronicles 001 alt',
      format: 'cbz',
      size_bytes: 2_000_000,
      age_seconds: 3_600,
      score: -1,
      outcome: 'temporarily-rejected',
      approved: false,
      rejections: ['Release too new'],
    },
  ];

  const oneApproved: ReleaseDecision[] = [
    {
      indexer_id: 8,
      guid: 'a1',
      indexer_name: 'IndexerTwo',
      title: 'Gadget Tales 002',
      format: 'cbz',
      size_bytes: 40_000_000,
      age_seconds: 3 * 86_400,
      score: 100,
      outcome: 'approved',
      approved: true,
      rejections: [],
    },
  ];

  it('FRG-UI-044 — an all-rejected search offers a confirm-gated Grab anyway that grabs with force, reasons staying visible', async () => {
    const { spy, fetcher } = fakeFetcher((_path, init) =>
      init?.method === 'POST' ? { id: 1, name: 'grab-release' } : allRejected,
    );
    const user = userEvent.setup();
    renderWithProviders(
      <InteractiveSearchOverlay issueId={7} onClose={() => {}} />,
      { fetcher },
    );

    // Every row is rejected/temporarily-rejected -> each offers "Grab anyway",
    // and NONE offers the plain approved one-click Grab.
    await screen.findByTestId('release-row-r1');
    expect(
      screen.queryByRole('button', { name: 'Grab Widget Chronicles 001' }),
    ).toBeNull();
    expect(
      screen.getByRole('button', { name: 'Grab Widget Chronicles 001 alt anyway' }),
    ).toBeInTheDocument();
    const anyway = screen.getByRole('button', {
      name: 'Grab Widget Chronicles 001 anyway',
    });

    // Activating it does NOT grab immediately — it interposes an explicit confirm.
    await user.click(anyway);
    expect(spy).not.toHaveBeenCalledWith(
      '/api/v1/release',
      expect.objectContaining({ method: 'POST' }),
    );
    const confirm = screen.getByRole('dialog', {
      name: 'Grab Widget Chronicles 001 anyway',
    });
    // The reasons being overridden are restated in the confirm...
    expect(within(confirm).getByTestId('confirm-force-reasons')).toHaveTextContent(
      'Below minimum size',
    );
    // ...and the row keeps its verbatim rejection reasons chip visible.
    const row = screen.getByTestId('release-row-r1');
    expect(
      within(row).getByRole('button', { name: 'Rejected — show reasons' }),
    ).toBeInTheDocument();

    // Confirming sends the grab WITH force: true.
    await user.click(within(confirm).getByRole('button', { name: 'Grab anyway' }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/release',
        expect.objectContaining({
          method: 'POST',
          body: { indexer_id: 7, guid: 'r1', force: true },
        }),
      ),
    );
  });

  it('FRG-UI-044 — an approved release keeps its one-click Grab with no confirm and no force flag', async () => {
    const { spy, fetcher } = fakeFetcher((_path, init) =>
      init?.method === 'POST' ? { id: 1, name: 'grab-release' } : oneApproved,
    );
    const user = userEvent.setup();
    renderWithProviders(
      <InteractiveSearchOverlay issueId={8} onClose={() => {}} />,
      { fetcher },
    );

    await screen.findByTestId('release-row-a1');
    await user.click(screen.getByRole('button', { name: 'Grab Gadget Tales 002' }));

    // Straight to the grab — the body carries NO force flag...
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/release',
        expect.objectContaining({
          method: 'POST',
          body: { indexer_id: 8, guid: 'a1' },
        }),
      ),
    );
    // ...and no confirm dialog was ever interposed.
    expect(screen.queryByRole('dialog', { name: /anyway/ })).toBeNull();
  });
});
