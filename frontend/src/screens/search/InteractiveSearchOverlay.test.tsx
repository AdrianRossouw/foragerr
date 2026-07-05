import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { mockReleases } from '../../test/mockData';
import { ApiRequestError, type Fetcher } from '../../api/fetcher';
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
    // Rejected rows never expose a grab button.
    expect(within(rejectedRow).queryByRole('button', { name: /^Grab / })).toBeNull();

    await user.click(
      screen.getByRole('button', { name: 'Grab Saga 041 (2017) (Digital)' }),
    );

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/release',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ indexer_id: 3, guid: 'guid-approved-best' }),
        }),
      ),
    );
    // The grabbed row's button is replaced by a grabbed marker.
    const row = screen.getByTestId('release-row-guid-approved-best');
    await waitFor(() => expect(within(row).getByText('Grabbed')).toBeInTheDocument());
  });

  it('FRG-UI-007 — an expired-cache grab surfaces the deterministic search-again error distinctly', async () => {
    const fetcher = vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        throw new ApiRequestError(404, EXPIRED_MESSAGE);
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
    const fetcher = vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        throw new ApiRequestError(500, 'boom');
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
