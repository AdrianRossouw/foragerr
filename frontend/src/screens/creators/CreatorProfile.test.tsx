import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { ApiRequestError, type FetcherInit } from '../../api/fetcher';
import { makeCreatorProfile, makeCreatorSeriesStat } from '../../test/mockData';
import type { CreatorProfileResource } from '../../api/types';
import { CreatorProfileRoute } from './CreatorProfile';

/**
 * FRG-UI-028 — Creator profile: gradient header (avatar/name/roles/publishers +
 * Follow), three stat columns from the API aggregates, "In your library" work
 * cards (cover, role chips, whole-series owned/total bar) that open the series,
 * and the standard not-found state for an unknown id. Fake fetcher only.
 */

function profileFetcher(profile: CreatorProfileResource) {
  const state: CreatorProfileResource = { ...profile };
  const { spy, fetcher } = fakeFetcher((path: string, options?: FetcherInit) => {
    const method = options?.method ?? 'GET';
    if (method === 'GET' && path === `/api/v1/creators/${state.id}`) {
      return { ...state };
    }
    if (method === 'PUT' && path === `/api/v1/creators/${state.id}/follow`) {
      state.followed = (options?.body as { followed: boolean }).followed;
      return { id: state.id, name: state.name, roles: state.roles, seriesCount: state.stats.seriesCount, followed: state.followed, works: [] };
    }
    // The follow onSettled invalidation refetches the whole creators family;
    // answer the (unused) list GET so that refetch doesn't error.
    if (method === 'GET' && path.startsWith('/api/v1/creators?')) {
      return { page: 1, pageSize: 200, sortKey: 'name', sortDirection: 'asc', totalRecords: 0, records: [], totalCreators: 0, followedCreators: 0 };
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  });
  return { spy, fetcher };
}

function renderProfile(fetcher: ReturnType<typeof profileFetcher>['fetcher'], id = 1) {
  return renderWithProviders(
    <Routes>
      <Route path="/creators/:id" element={<CreatorProfileRoute />} />
      <Route path="/creators" element={<div data-testid="grid-stub" />} />
      <Route path="/series/:id" element={<div data-testid="series-stub" />} />
    </Routes>,
    { fetcher, route: `/creators/${id}` },
  );
}

describe('FRG-UI-028: creator profile', () => {
  it('FRG-UI-028 — the header shows avatar/name/roles/publishers and the stat columns equal the API', async () => {
    const profile = makeCreatorProfile({
      series: [
        makeCreatorSeriesStat({ seriesId: 7, title: 'Invincible', publisher: 'Image', ownedIssues: 3, totalIssues: 12 }),
        makeCreatorSeriesStat({ seriesId: 8, title: 'Tech Jacket', publisher: 'Skybound', ownedIssues: 5, totalIssues: 20 }),
      ],
    });
    const { fetcher } = profileFetcher(profile);
    renderProfile(fetcher);

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Robert Kirkman' })).toBeInTheDocument(),
    );
    // Large initials avatar + roles line + publishers line, scoped to the header
    // (a "Writer" role chip also appears on the work cards below).
    const header = screen.getByRole('heading', { name: 'Robert Kirkman' }).closest('header')!;
    expect(within(header).getByText('RK')).toBeInTheDocument();
    expect(within(header).getByText('Writer')).toBeInTheDocument();
    expect(within(header).getByText('Image · Skybound')).toBeInTheDocument();

    // Stat columns: Series, owned-of-total, publishers.
    expect(screen.getByTestId('stat-series')).toHaveTextContent('2');
    expect(screen.getByTestId('stat-issues')).toHaveTextContent('8 / 32');
    expect(screen.getByTestId('stat-publishers')).toHaveTextContent('2');
  });

  it('FRG-UI-028 — the Follow button toggles via the follow PUT', async () => {
    const { spy, fetcher } = profileFetcher(makeCreatorProfile({ followed: false }));
    renderProfile(fetcher);
    const user = userEvent.setup();

    const btn = await screen.findByRole('button', { name: 'Follow Robert Kirkman' });
    await user.click(btn);

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/creators/1/follow', {
        method: 'PUT',
        body: { followed: true },
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Unfollow Robert Kirkman' })).toBeInTheDocument(),
    );
  });

  it('FRG-UI-028 — work cards show the local cover, role chips, and the owned/total bar, and open the series', async () => {
    const profile = makeCreatorProfile({
      series: [
        makeCreatorSeriesStat({
          seriesId: 7,
          title: 'Invincible',
          publisher: 'Image',
          roles: ['writer'],
          ownedIssues: 3,
          totalIssues: 12,
        }),
      ],
    });
    const { fetcher } = profileFetcher(profile);
    renderProfile(fetcher);
    const user = userEvent.setup();

    const card = await screen.findByTestId('work-card-7');
    // Local cover endpoint, this creator's role chip, whole-series progress bar.
    expect(within(card).getByAltText('Invincible cover')).toHaveAttribute(
      'src',
      '/api/v1/series/7/cover',
    );
    expect(within(card).getByText('Writer')).toBeInTheDocument();
    expect(
      within(card).getByRole('status', { name: '3 of 12 issues on disk' }),
    ).toBeInTheDocument();

    await user.click(card);
    expect(screen.getByTestId('series-stub')).toBeInTheDocument();
  });

  it('FRG-UI-028 — an unknown creator id renders the standard not-found state', async () => {
    const { fetcher } = fakeFetcher((path: string, options?: FetcherInit) => {
      const method = options?.method ?? 'GET';
      if (method === 'GET' && path === '/api/v1/creators/999') {
        throw new ApiRequestError(404, { message: 'creator 999 not found', errors: [] }, path);
      }
      throw new Error(`unexpected request: ${method} ${path}`);
    });
    renderProfile(fetcher, 999);

    await waitFor(() =>
      expect(screen.getByTestId('creator-not-found')).toBeInTheDocument(),
    );
    expect(screen.getByText('Creator not found')).toBeInTheDocument();
  });
});
