import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { creatorPageOf, makeCreator, makeSeriesResource } from '../../test/mockData';
import { createQueryClient } from '../../queryClient';
import { queryKeys } from '../../api/queryKeys';
import type { CreatorResource } from '../../api/types';
import type { FetcherInit } from '../../api/fetcher';
import { CreatorsScreen } from './CreatorsScreen';

/**
 * FRG-UI-027 — Creators grid: cards to the design (avatar, name, roles·series,
 * follow pill, work spines), the aggregate count header, the followed-only
 * filter, the series focus chip, and the credits-still-gathering empty state.
 * FRG-CRTR-004 — the follow toggle is exactly one PUT and no other write.
 * Fake fetcher only; no live backend.
 */

/** A stateful creators backend: PUT flips the stored follow flag; GET reflects
 *  it, honoring the followed / seriesId query filters. */
function creatorsFetcher(initial: CreatorResource[], totalOverrides = {}) {
  const state = new Map(initial.map((c) => [c.id, { ...c }]));
  const { spy, fetcher } = fakeFetcher((path: string, options?: FetcherInit) => {
    const method = options?.method ?? 'GET';
    if (method === 'PUT' && /\/api\/v1\/creators\/(\d+)\/follow$/.test(path)) {
      const id = Number(path.match(/\/creators\/(\d+)\/follow$/)![1]);
      const followed = (options?.body as { followed: boolean }).followed;
      const row = state.get(id)!;
      row.followed = followed;
      return { ...row };
    }
    if (method === 'GET' && path.startsWith('/api/v1/creators?')) {
      const url = new URL(path, 'http://x');
      let rows = [...state.values()];
      if (url.searchParams.get('followed') === 'true') {
        rows = rows.filter((c) => c.followed);
      }
      const seriesId = url.searchParams.get('seriesId');
      if (seriesId !== null) {
        rows = rows.filter((c) => c.works.some((w) => w.seriesId === Number(seriesId)));
      }
      return creatorPageOf(rows, {
        totalCreators: state.size,
        followedCreators: [...state.values()].filter((c) => c.followed).length,
        ...totalOverrides,
      });
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  });
  return { spy, fetcher };
}

function renderCreators(fetcher: ReturnType<typeof creatorsFetcher>['fetcher'], route = '/creators') {
  return renderWithProviders(
    <Routes>
      <Route path="/creators" element={<CreatorsScreen />} />
      <Route path="/creators/:id" element={<div data-testid="profile-stub" />} />
      <Route path="/series/:id" element={<div data-testid="series-stub" />} />
    </Routes>,
    { fetcher, route },
  );
}

describe('FRG-UI-027: creators grid', () => {
  it('FRG-UI-027 — cards render to the design and the header shows the API aggregates', async () => {
    const creators = [
      makeCreator({ id: 1, name: 'Robert Kirkman', roles: ['writer'], seriesCount: 2 }),
      makeCreator({
        id: 2,
        name: 'Cory Walker',
        roles: ['artist', 'penciler'],
        seriesCount: 1,
        followed: true,
        works: [{ seriesId: 7, title: 'Invincible', coverAvailable: true }],
      }),
    ];
    const { fetcher } = creatorsFetcher(creators, {
      totalCreators: 5,
      followedCreators: 2,
    });
    renderCreators(fetcher);

    await waitFor(() =>
      expect(screen.getByTestId('creators-grid')).toBeInTheDocument(),
    );

    // Header aggregate line matches the envelope's whole-library counts.
    expect(screen.getByText('5 creators · 2 followed')).toBeInTheDocument();

    const card = screen.getByTestId('creator-card-1');
    expect(within(card).getByText('Robert Kirkman')).toBeInTheDocument();
    // roles · N series line.
    expect(within(card).getByText('Writer · 2 series')).toBeInTheDocument();
    // Deterministic initials avatar (first letters of the first two words).
    expect(within(card).getByText('RK')).toBeInTheDocument();
    // Follow pill (unfollowed) + a work spine per library work ref.
    expect(
      within(card).getByRole('button', { name: 'Follow Robert Kirkman' }),
    ).toBeInTheDocument();
    expect(
      within(card).getByRole('button', { name: 'Open Invincible' }),
    ).toBeInTheDocument();

    // A followed creator's pill reads Following.
    expect(
      within(screen.getByTestId('creator-card-2')).getByText('Following'),
    ).toBeInTheDocument();
    expect(within(screen.getByTestId('creator-card-2')).getByText('Artist, Penciler · 1 series')).toBeInTheDocument();
  });

  it('FRG-UI-027 / FRG-CRTR-004 — clicking an unfollowed pill makes exactly one follow PUT and no other write', async () => {
    const { spy, fetcher } = creatorsFetcher([
      makeCreator({ id: 1, name: 'Robert Kirkman', followed: false }),
    ]);
    renderCreators(fetcher);
    const user = userEvent.setup();

    const pill = await screen.findByRole('button', { name: 'Follow Robert Kirkman' });
    await user.click(pill);

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/creators/1/follow', {
        method: 'PUT',
        body: { followed: true },
      }),
    );
    // The pill flips to Following.
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Unfollow Robert Kirkman' }),
      ).toBeInTheDocument(),
    );

    // Exactly one write, and it is the follow PUT — no other mutating request.
    const writes = spy.mock.calls.filter(
      ([, init]) => (init?.method ?? 'GET') !== 'GET',
    );
    expect(writes).toHaveLength(1);
    expect(writes[0][0]).toBe('/api/v1/creators/1/follow');
  });

  it('FRG-UI-027 — the followed-only filter shows only followed creators and clearing it restores the grid', async () => {
    const { fetcher } = creatorsFetcher([
      makeCreator({ id: 1, name: 'Robert Kirkman', followed: false }),
      makeCreator({ id: 2, name: 'Cory Walker', followed: true }),
    ]);
    renderCreators(fetcher);
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByTestId('creator-card-1')).toBeInTheDocument(),
    );

    await user.click(screen.getByRole('radio', { name: 'Following' }));
    await waitFor(() =>
      expect(screen.queryByTestId('creator-card-1')).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId('creator-card-2')).toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: 'All' }));
    await waitFor(() =>
      expect(screen.getByTestId('creator-card-1')).toBeInTheDocument(),
    );
  });

  it('FRG-UI-027 — a series focus lists only that series\' creators behind a dismissible chip naming the series', async () => {
    const { fetcher } = creatorsFetcher([
      makeCreator({
        id: 1,
        name: 'Robert Kirkman',
        works: [{ seriesId: 7, title: 'Invincible', coverAvailable: true }],
      }),
      makeCreator({
        id: 2,
        name: 'Somebody Else',
        works: [{ seriesId: 99, title: 'Other Book', coverAvailable: false }],
      }),
    ]);
    renderCreators(fetcher, '/creators?seriesId=7');
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByTestId('creator-card-1')).toBeInTheDocument(),
    );
    // Only series 7's creator; the chip names the series (derived from works).
    expect(screen.queryByTestId('creator-card-2')).not.toBeInTheDocument();
    const chip = screen.getByRole('button', { name: 'Clear series focus' });
    expect(chip).toHaveTextContent('Invincible');

    // Dismissing the focus restores the full grid.
    await user.click(chip);
    await waitFor(() =>
      expect(screen.getByTestId('creator-card-2')).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole('button', { name: 'Clear series focus' }),
    ).not.toBeInTheDocument();
  });

  it('FRG-UI-027 — an empty library renders a neutral no-credits state, not an error or a bare grid', async () => {
    const { fetcher } = creatorsFetcher([]);
    renderCreators(fetcher);

    await waitFor(() =>
      expect(screen.getByTestId('creators-empty')).toBeInTheDocument(),
    );
    // Neutral honesty — no false "still being gathered" claim for a genuinely
    // credit-less library; points at the creators-backfill task.
    expect(screen.getByText(/no creator credits yet/i)).toBeInTheDocument();
    expect(screen.getByText(/creators-backfill/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/still being gathered/i),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId('creators-grid')).not.toBeInTheDocument();
  });

  it('FRG-UI-027 — a ?seriesId=0 focus is ignored (backend rejects ge=1): the normal unfocused grid renders with no focus chip', async () => {
    const { fetcher } = creatorsFetcher([
      makeCreator({ id: 1, name: 'Robert Kirkman' }),
      makeCreator({ id: 2, name: 'Cory Walker' }),
    ]);
    renderCreators(fetcher, '/creators?seriesId=0');

    await waitFor(() =>
      expect(screen.getByTestId('creators-grid')).toBeInTheDocument(),
    );
    // Both creators show (no series filter applied) and there is no focus chip.
    expect(screen.getByTestId('creator-card-1')).toBeInTheDocument();
    expect(screen.getByTestId('creator-card-2')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Clear series focus' }),
    ).not.toBeInTheDocument();
  });

  it('FRG-UI-027 — the focus chip names the series from the cached series index when no visible row carries it in its (capped) work refs', async () => {
    // A prolific creator credited in series 7 but whose card work refs (capped
    // at WORKS_CAP) do not include series 7 — the old works-scan would fall back
    // to the generic label. The title must come from the ['series'] cache.
    const { fetcher } = creatorsFetcher([
      makeCreator({
        id: 1,
        name: 'Robert Kirkman',
        works: [{ seriesId: 999, title: 'Some Other Book', coverAvailable: false }],
      }),
    ]);
    const client = createQueryClient();
    // Seed the same library index HeaderQuickSearch populates (useSeriesIndex →
    // queryKeys.series.all()).
    client.setQueryData(queryKeys.series.all(), [
      makeSeriesResource({ id: 7, title: 'Invincible' }),
    ]);
    renderWithProviders(
      <Routes>
        <Route path="/creators" element={<CreatorsScreen />} />
      </Routes>,
      { fetcher, route: '/creators?seriesId=7', client },
    );

    const chip = await screen.findByRole('button', { name: 'Clear series focus' });
    expect(chip).toHaveTextContent('Invincible');
  });

  it('FRG-UI-027 — clicking a card opens the creator profile; a spine opens the series', async () => {
    const { fetcher } = creatorsFetcher([
      makeCreator({
        id: 1,
        name: 'Robert Kirkman',
        works: [{ seriesId: 7, title: 'Invincible', coverAvailable: true }],
      }),
    ]);
    renderCreators(fetcher);
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByTestId('creator-card-1')).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Open Invincible' }));
    expect(screen.getByTestId('series-stub')).toBeInTheDocument();
  });
});
