import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route, useLocation } from 'react-router-dom';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { ApiRequestError, type FetcherInit } from '../../api/fetcher';
import {
  makeBibliographyEntry,
  makeCreatorBibliography,
  makeCreatorProfile,
  makeCreatorSeriesStat,
} from '../../test/mockData';
import type {
  AddSeriesNavigationState,
  CreatorBibliography,
  CreatorProfileResource,
} from '../../api/types';
import { CreatorProfileRoute } from './CreatorProfile';

/**
 * FRG-UI-028 — Creator profile: gradient header (avatar/name/roles/publishers +
 * Follow), three stat columns from the API aggregates, "In your library" work
 * cards (cover, role chips, whole-series owned/total bar) that open the series,
 * the "More from" bibliography cards with add hand-offs (+ pending/empty
 * states), and the standard not-found state for an unknown id. Fake fetcher only.
 */

function profileFetcher(
  profile: CreatorProfileResource,
  biblio: CreatorBibliography = makeCreatorBibliography([]),
) {
  const state: CreatorProfileResource = { ...profile };
  const { spy, fetcher } = fakeFetcher((path: string, options?: FetcherInit) => {
    const method = options?.method ?? 'GET';
    if (method === 'GET' && path === `/api/v1/creators/${state.id}/bibliography`) {
      return { ...biblio };
    }
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

/** Probe route capturing the prefillTerm handed to /add. */
function AddProbe() {
  const state = useLocation().state as AddSeriesNavigationState | null;
  return <div data-testid="add-stub">{state?.prefillTerm ?? ''}</div>;
}

function renderProfile(fetcher: ReturnType<typeof profileFetcher>['fetcher'], id = 1) {
  return renderWithProviders(
    <Routes>
      <Route path="/creators/:id" element={<CreatorProfileRoute />} />
      <Route path="/creators" element={<div data-testid="grid-stub" />} />
      <Route path="/series/:id" element={<div data-testid="series-stub" />} />
      <Route path="/add" element={<AddProbe />} />
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
      if (
        method === 'GET' &&
        (path === '/api/v1/creators/999' ||
          path === '/api/v1/creators/999/bibliography')
      ) {
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

  it('FRG-UI-028 — More-from cards render from a fresh cache and hand off to /add prefilled', async () => {
    const biblio = makeCreatorBibliography(
      [
        makeBibliographyEntry({ cvVolumeId: 4050, title: 'Oblivion Song', publisher: 'Image', startYear: 2018, countOfIssues: 36 }),
        makeBibliographyEntry({ cvVolumeId: 4051, title: 'Die!Die!Die!', publisher: 'Image', startYear: 2018, countOfIssues: null }),
      ],
      'fresh',
    );
    const { fetcher } = profileFetcher(makeCreatorProfile(), biblio);
    renderProfile(fetcher);
    const user = userEvent.setup();

    // Section shell: label + count chip + the not-in-library subline.
    const section = await screen.findByTestId('creator-more-from');
    expect(within(section).getByText('More from Robert Kirkman')).toBeInTheDocument();
    expect(within(section).getByText('2')).toBeInTheDocument();
    expect(
      within(section).getByText(/Not in your library yet/i),
    ).toBeInTheDocument();

    // A card carries the title (tinted placeholder + heading = 2 nodes), the
    // publisher/year/count meta line, and an Add button.
    const card = within(section).getByTestId('more-card-4050');
    expect(within(card).getAllByText('Oblivion Song').length).toBeGreaterThanOrEqual(1);
    expect(within(card).getByText('Image · 2018 · 36 issues')).toBeInTheDocument();

    // Add hands off to the standard add flow prefilled with the volume title.
    await user.click(
      within(card).getByRole('button', { name: 'Add Oblivion Song to library' }),
    );
    await waitFor(() =>
      expect(screen.getByTestId('add-stub')).toHaveTextContent('Oblivion Song'),
    );
  });

  it('FRG-UI-028 — a pending bibliography with no rows shows the gathering state, no section shell', async () => {
    const { fetcher } = profileFetcher(
      makeCreatorProfile(),
      makeCreatorBibliography([], 'pending'),
    );
    renderProfile(fetcher);

    await waitFor(() =>
      expect(screen.getByTestId('creator-more-gathering')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('creator-more-gathering')).toHaveTextContent(
      /Gathering Robert Kirkman.s bibliography from ComicVine/i,
    );
    // No section shell (label/subline) while gathering an empty cache.
    expect(screen.queryByTestId('creator-more-from')).not.toBeInTheDocument();
    expect(screen.queryByText(/Not in your library yet/i)).not.toBeInTheDocument();
  });

  it('FRG-UI-028 — a fresh, empty bibliography renders no More-from section at all', async () => {
    const { fetcher } = profileFetcher(
      makeCreatorProfile(),
      makeCreatorBibliography([], 'fresh'),
    );
    renderProfile(fetcher);

    // Wait until the profile itself has rendered, then assert the section is absent.
    await screen.findByTestId('creator-works');
    expect(screen.queryByTestId('creator-more-from')).not.toBeInTheDocument();
    expect(screen.queryByTestId('creator-more-gathering')).not.toBeInTheDocument();
  });
});
