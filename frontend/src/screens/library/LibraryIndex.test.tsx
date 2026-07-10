import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { UserEvent } from '@testing-library/user-event';
import { Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import {
  makeGroupMember,
  makeMockLibrary,
  makeSeriesGroup,
  makeSeriesResource,
  makeStats,
  pageOf,
} from '../../test/mockData';
import { useUiStore } from '../../store/uiStore';
import type { FetcherInit } from '../../api/fetcher';
import type { SeriesGroupResource, SeriesResource } from '../../api/types';
import { LibraryIndex } from './LibraryIndex';

/**
 * FRG-UI-003 — Library index screen (M4 redesign): three view modes
 * (Posters / Overview / Table), poster-size control, count line, and the
 * Options / Sort / Filter raised menus with persisted selections. FRG-UI-021 —
 * the grouped overlay (stacked poster cards + collapsible row/table headers).
 * FRG-UI-022 — collected-edition badge + editions filter. All data rides the
 * fake fetcher; no live backend.
 */

beforeEach(() => {
  localStorage.clear();
  useUiStore.setState({
    libraryViewMode: 'poster',
    libraryPosterSize: 'm',
    librarySortKey: 'title',
    libraryStatusFilter: 'all',
    libraryGroupByFranchise: false,
    libraryCollectedFilter: 'all',
    interactiveSearchIssueId: null,
  });
});

function libraryFetcher(records: SeriesResource[]) {
  return fakeFetcher((path) => {
    if (path.startsWith('/api/v1/series?')) return pageOf(records);
    throw new Error(`unexpected request: ${path}`);
  });
}

function renderLibrary(records: SeriesResource[]) {
  const { spy, fetcher } = libraryFetcher(records);
  const utils = renderWithProviders(
    <Routes>
      <Route path="/" element={<LibraryIndex />} />
      <Route path="/series/:id" element={<div data-testid="detail-stub" />} />
      <Route path="/add" element={<div data-testid="add-stub" />} />
      <Route path="/library-import" element={<div data-testid="import-stub" />} />
    </Routes>,
    { fetcher },
  );
  return { spy, ...utils };
}

/** Open a raised menu only if its panel is not already showing. */
async function ensureMenuOpen(user: UserEvent, trigger: string, panel: string) {
  if (!screen.queryByTestId(panel)) await user.click(screen.getByTestId(trigger));
}

/** Open the Sort menu (if needed) and pick an option by testid. */
async function pickSort(user: UserEvent, testId: string) {
  await ensureMenuOpen(user, 'sort-menu-trigger', 'sort-menu');
  await user.click(screen.getByTestId(testId));
}

/** Open the Filter menu (if needed) and pick an option by testid. */
async function pickFilter(user: UserEvent, testId: string) {
  await ensureMenuOpen(user, 'filter-menu-trigger', 'filter-menu');
  await user.click(screen.getByTestId(testId));
}

/** Toggle group-volumes (lives inside the Options menu). */
async function toggleGrouping(user: UserEvent) {
  await ensureMenuOpen(user, 'options-menu-trigger', 'options-menu');
  await user.click(screen.getByTestId('group-by-toggle'));
}

/** Titles rendered in the poster grid (cards must carry no book-type badge). */
function posterTitles(): (string | null)[] {
  return screen
    .getAllByTestId('series-card')
    .map((card) => within(card).getByTitle(/.+/).textContent);
}

describe('FRG-UI-003: library index', () => {
  it('FRG-UI-003 — poster grid renders 50+ series with title, monitored state, counts and LOCAL covers', async () => {
    const library = makeMockLibrary(55);
    renderLibrary(library);

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(55),
    );

    const grid = screen.getByTestId('library-poster-grid');
    const firstCard = screen.getAllByTestId('series-card')[0];
    expect(within(firstCard).getByText(/Chronicles/)).toBeInTheDocument();
    // Monitored bookmark + owned/total progress strip are present.
    expect(within(firstCard).getByLabelText(/Monitored|Unmonitored/)).toBeInTheDocument();
    expect(within(firstCard).getByRole('status')).toBeInTheDocument();

    // Every poster img points at the local cover endpoint, versioned by
    // cover_cached_at — never an external ComicVine image host.
    const images = grid.querySelectorAll('img');
    expect(images.length).toBe(55);
    for (const img of images) {
      expect(img.getAttribute('src')).toMatch(/^\/api\/v1\/series\/\d+\/cover\?v=.+$/);
    }
  });

  it('FRG-UI-003 — a series with no cached cover renders no <img> (avoids a known 404); a cached one carries a versioned src', async () => {
    const library = makeMockLibrary(3).map((s, i) =>
      i === 0 ? { ...s, cover_cached_at: null } : s,
    );
    renderLibrary(library);

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(3),
    );

    const cards = screen.getAllByTestId('series-card');
    const uncachedCard = cards.find((c) => c.id === 'series-card-1');
    expect(uncachedCard).toBeDefined();
    expect(within(uncachedCard as HTMLElement).queryByRole('img')).not.toBeInTheDocument();

    // The other series DO have a cached cover and render a versioned img
    // pointing at the LOCAL cover endpoint.
    const cachedCard = cards.find((c) => c.id === 'series-card-2');
    const img = within(cachedCard as HTMLElement).getByRole('img');
    expect(img.getAttribute('src')).toBe(
      `/api/v1/series/2/cover?v=${encodeURIComponent('2026-07-01T00:00:00Z')}`,
    );
  });

  it('FRG-UI-003 — the view switcher covers Posters, Overview and Table and restores each layout', async () => {
    renderLibrary(makeMockLibrary(5));
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByTestId('library-poster-grid')).toBeInTheDocument(),
    );

    await user.click(screen.getByRole('button', { name: 'Overview' }));
    expect(screen.getByTestId('library-overview')).toBeInTheDocument();
    expect(screen.getAllByTestId('series-row')).toHaveLength(5);
    expect(screen.queryByTestId('library-poster-grid')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Table' }));
    const table = screen.getByTestId('library-table');
    expect(screen.getAllByTestId('series-row')).toHaveLength(5);
    expect(within(table).getByText('Title')).toBeInTheDocument();
    expect(within(table).getByText('Issues')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Posters' }));
    expect(screen.getByTestId('library-poster-grid')).toBeInTheDocument();
    expect(screen.queryByTestId('library-table')).not.toBeInTheDocument();
  });

  it('FRG-UI-003 — the poster-size control re-lays the grid and the choice persists', async () => {
    renderLibrary(makeMockLibrary(4));
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByTestId('library-poster-grid')).toBeInTheDocument(),
    );
    // Default M ≈ 162px min column.
    expect(screen.getByTestId('library-poster-grid').getAttribute('style')).toContain(
      '162px',
    );

    await user.click(screen.getByTestId('options-menu-trigger'));
    await user.click(screen.getByTestId('poster-size-l'));

    expect(screen.getByTestId('library-poster-grid').getAttribute('style')).toContain(
      '196px',
    );
    expect(useUiStore.getState().libraryPosterSize).toBe('l');
    // Persisted to localStorage so it survives a reload.
    const persisted = JSON.parse(localStorage.getItem('foragerr-library-view')!);
    expect(persisted.state.libraryPosterSize).toBe('l');
  });

  it('FRG-UI-003 — Sort and Filter menus and the text filter drive the list', async () => {
    const records = [
      makeSeriesResource({
        id: 1,
        title: 'Saga',
        sort_title: 'saga',
        start_year: 2012,
        monitored: true,
        statistics: makeStats({ issue_count: 20, file_count: 20 }),
      }),
      makeSeriesResource({
        id: 2,
        title: 'Bone',
        sort_title: 'bone',
        start_year: 1991,
        monitored: false,
        statistics: makeStats({ issue_count: 55, file_count: 40, missing_count: 15 }),
      }),
      makeSeriesResource({
        id: 3,
        title: 'Alpha Flight',
        sort_title: 'alpha flight',
        start_year: 1983,
        monitored: true,
        statistics: makeStats({ issue_count: 30, file_count: 10, missing_count: 20 }),
      }),
    ];
    renderLibrary(records);
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getAllByTestId('series-card')).toHaveLength(3));

    // Default title sort: alphabetic by sort_title.
    expect(posterTitles()).toEqual(['Alpha Flight', 'Bone', 'Saga']);

    // Sort by Year → newest start year first; the active option shows its check.
    await pickSort(user, 'sort-year');
    expect(posterTitles()).toEqual(['Saga', 'Bone', 'Alpha Flight']);
    expect(screen.getByTestId('sort-year').getAttribute('data-active')).toBe('true');
    expect(screen.getByTestId('sort-title').getAttribute('data-active')).toBe('false');

    // Each Filter option shows its live count; picking Monitored narrows the list.
    await user.click(screen.getByTestId('filter-menu-trigger'));
    expect(within(screen.getByTestId('status-filter-all')).getByText('3')).toBeInTheDocument();
    expect(
      within(screen.getByTestId('status-filter-monitored')).getByText('2'),
    ).toBeInTheDocument();
    await user.click(screen.getByTestId('status-filter-monitored'));
    expect(posterTitles()).toEqual(['Saga', 'Alpha Flight']);

    // Text filter narrows further (applied on top of the status filter).
    await user.type(screen.getByLabelText('Filter series'), 'saga');
    expect(posterTitles()).toEqual(['Saga']);
  });

  it('FRG-UI-003 — the count line reports total, monitored (accent) and with-missing counts', async () => {
    const records = [
      makeSeriesResource({ id: 1, monitored: true, statistics: makeStats({ missing_count: 3 }) }),
      makeSeriesResource({ id: 2, monitored: true, statistics: makeStats({ missing_count: 0 }) }),
      makeSeriesResource({ id: 3, monitored: false, statistics: makeStats({ missing_count: 5 }) }),
    ];
    renderLibrary(records);

    const line = await screen.findByTestId('library-count-line');
    expect(within(line).getByText('3 comics')).toBeInTheDocument();
    expect(within(line).getByText('2 monitored')).toBeInTheDocument();
    expect(within(line).getByText('2 with missing issues')).toBeInTheDocument();
  });

  it('FRG-UI-003 — a click in the content region closes an open toolbar menu', async () => {
    renderLibrary(makeMockLibrary(3));
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByTestId('library-poster-grid')).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId('sort-menu-trigger'));
    expect(screen.getByTestId('sort-menu')).toBeInTheDocument();

    // Clicking the count line (content region) dismisses the menu.
    await user.click(screen.getByTestId('library-count-line'));
    expect(screen.queryByTestId('sort-menu')).not.toBeInTheDocument();
  });

  it('FRG-UI-003 — a "no match" note replaces the grid when nothing matches the text filter', async () => {
    renderLibrary([makeSeriesResource({ id: 1, title: 'Saga', sort_title: 'saga' })]);
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByTestId('series-card')).toBeInTheDocument());
    await user.type(screen.getByLabelText('Filter series'), 'zzz-nothing');

    expect(screen.getByText('No comics match your search.')).toBeInTheDocument();
    expect(screen.queryByTestId('library-poster-grid')).not.toBeInTheDocument();
  });

  it('FRG-UI-003 — a series card / overview row / table row opens its detail route', async () => {
    renderLibrary([makeSeriesResource({ id: 9, title: 'Saga', sort_title: 'saga' })]);
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByTestId('series-card')).toBeInTheDocument());

    // Overview + table rows link to the detail route (checked before navigating,
    // since navigation unmounts the index).
    await user.click(screen.getByRole('button', { name: 'Overview' }));
    expect(screen.getByTestId('series-row')).toHaveAttribute('href', '/series/9');
    await user.click(screen.getByRole('button', { name: 'Table' }));
    expect(screen.getByRole('link', { name: 'Saga' })).toHaveAttribute(
      'href',
      '/series/9',
    );

    // Clicking a poster card actually navigates.
    await user.click(screen.getByRole('button', { name: 'Posters' }));
    await user.click(screen.getByTestId('series-card'));
    expect(screen.getByTestId('detail-stub')).toBeInTheDocument();
  });

  it('FRG-UI-003 — Add New / Import toolbar actions navigate to their screens', async () => {
    renderLibrary([makeSeriesResource({ id: 1 })]);
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByTestId('series-card')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Add New' }));
    expect(screen.getByTestId('add-stub')).toBeInTheDocument();
  });

  it('FRG-UI-003 — view/size/sort/filter selections persist (localStorage round-trip) and stale values sanitize', () => {
    // Round-trip: setting the preferences writes exactly the persisted partition.
    const s = useUiStore.getState();
    s.setLibraryViewMode('table');
    s.setLibraryPosterSize('l');
    s.setLibrarySortKey('year');
    s.setLibraryStatusFilter('monitored');
    s.setLibraryCollectedFilter('collected');

    const persisted = JSON.parse(localStorage.getItem('foragerr-library-view')!);
    expect(persisted.state).toEqual({
      libraryViewMode: 'table',
      libraryPosterSize: 'l',
      librarySortKey: 'year',
      libraryStatusFilter: 'monitored',
      libraryCollectedFilter: 'collected',
    });

    // A stale session (an old 'added' sort, a bogus mode/size) sanitizes back to
    // defaults on rehydration rather than crashing a render.
    localStorage.setItem(
      'foragerr-library-view',
      JSON.stringify({
        version: 0,
        state: {
          libraryViewMode: 'mosaic',
          libraryPosterSize: 'xl',
          librarySortKey: 'added',
          libraryStatusFilter: 'weird',
          libraryCollectedFilter: 'nope',
        },
      }),
    );
    useUiStore.persist.rehydrate();
    const after = useUiStore.getState();
    expect(after.libraryViewMode).toBe('poster');
    expect(after.libraryPosterSize).toBe('m');
    expect(after.librarySortKey).toBe('title');
    expect(after.libraryStatusFilter).toBe('all');
    expect(after.libraryCollectedFilter).toBe('all');
  });
});

/**
 * FRG-UI-021 — Grouped (franchise) library overlay: poster mode stacks a
 * multi-run franchise into ONE card (layered shadow, `N vols` chip, summed
 * owned/total); row/table modes nest runs under a collapsible franchise header
 * with a roll-up stat; single-run franchises render as ordinary cards/rows;
 * grouping is display-only; and the group rename/reassign affordance fires the
 * group-edit mutation (FRG-SER-017).
 */

const GROUPED_SERIES: SeriesResource[] = [
  makeSeriesResource({
    id: 1,
    title: 'Batman (2011)',
    sort_title: 'batman (2011)',
    start_year: 2011,
    series_group_id: 1,
  }),
  makeSeriesResource({
    id: 2,
    title: 'Batman (2016)',
    sort_title: 'batman (2016)',
    start_year: 2016,
    series_group_id: 1,
  }),
  makeSeriesResource({
    id: 3,
    title: 'Saga',
    sort_title: 'saga',
    series_group_id: null,
  }),
];

const GROUPED_GROUPS: SeriesGroupResource[] = [
  makeSeriesGroup({
    id: 1,
    kind: 'group',
    title: 'Batman',
    series: [
      makeGroupMember({ id: 1, start_year: 2011 }),
      makeGroupMember({ id: 2, start_year: 2016 }),
    ],
    series_count: 2,
    issue_count: 50,
    owned_count: 30,
  }),
  makeSeriesGroup({
    id: null,
    kind: 'series',
    title: 'Saga',
    series: [makeGroupMember({ id: 3 })],
  }),
];

function groupedFetcher(records: SeriesResource[], groups: SeriesGroupResource[]) {
  return fakeFetcher((path: string, init?: FetcherInit) => {
    if (path.startsWith('/api/v1/series/groups?')) {
      return pageOf(groups, { sortKey: 'title' });
    }
    if (path.startsWith('/api/v1/series?')) return pageOf(records);
    const put = path.match(/^\/api\/v1\/series\/(\d+)$/);
    if (put && init?.method === 'PUT') {
      return makeSeriesResource({ id: Number(put[1]) });
    }
    throw new Error(`unexpected request: ${path}`);
  });
}

function renderGrouped(
  records: SeriesResource[] = GROUPED_SERIES,
  groups: SeriesGroupResource[] = GROUPED_GROUPS,
) {
  const { spy, fetcher } = groupedFetcher(records, groups);
  const utils = renderWithProviders(
    <Routes>
      <Route path="/" element={<LibraryIndex />} />
      <Route path="/series/:id" element={<div data-testid="detail-stub" />} />
    </Routes>,
    { fetcher },
  );
  return { spy, ...utils };
}

describe('FRG-UI-021: grouped library view', () => {
  it('FRG-UI-021 — grouped posters stack a multi-run franchise into ONE card; single-run stays an ordinary card', async () => {
    renderGrouped();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(3),
    );
    await toggleGrouping(user);

    // Batman becomes a single stacked franchise card (not two nested cards);
    // Saga stays an ordinary poster card.
    await waitFor(() =>
      expect(screen.getAllByTestId('franchise-group')).toHaveLength(1),
    );
    const stack = screen.getByTestId('franchise-group');
    expect(within(stack).getByText('Batman')).toBeInTheDocument();
    // Summed owned/total across the franchise + an `N vols` chip.
    expect(within(stack).getByText('30 / 50')).toBeInTheDocument();
    expect(within(stack).getByText(/2 vols/)).toBeInTheDocument();
    // Saga is the only ordinary card.
    expect(screen.getAllByTestId('series-card')).toHaveLength(1);
    expect(screen.getByText('Saga')).toBeInTheDocument();
  });

  it('FRG-UI-021 — a stacked franchise card opens the newest run detail', async () => {
    renderGrouped();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(3),
    );
    await toggleGrouping(user);
    await waitFor(() =>
      expect(screen.getByTestId('franchise-group')).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId('franchise-group'));
    expect(screen.getByTestId('detail-stub')).toBeInTheDocument();
  });

  it('FRG-UI-021 — in a row/table context grouped runs nest under one collapsible franchise header', async () => {
    renderGrouped();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(3),
    );
    await user.click(screen.getByRole('button', { name: 'Table' }));
    await toggleGrouping(user);

    await waitFor(() =>
      expect(screen.getAllByTestId('franchise-group')).toHaveLength(1),
    );
    const group = screen.getByTestId('franchise-group');
    const header = within(group).getByTestId('franchise-group-header');
    expect(within(header).getByText('Batman')).toBeInTheDocument();
    // Roll-up straight from the projection: owned/total + run count.
    expect(within(header).getByText('30 / 50')).toBeInTheDocument();
    expect(within(header).getByText('2 runs')).toBeInTheDocument();

    // The two runs nest inside the franchise; Saga is a single-run row outside.
    expect(within(group).getAllByTestId('series-row')).toHaveLength(2);
    expect(within(group).queryByText('Saga')).not.toBeInTheDocument();
    expect(screen.getByText('Saga')).toBeInTheDocument();

    // Collapsing the header hides the member runs; Saga stays visible.
    await user.click(within(header).getByTestId('franchise-collapse'));
    expect(screen.queryByTestId('franchise-members')).not.toBeInTheDocument();
    expect(screen.getByText('Saga')).toBeInTheDocument();
  });

  it('FRG-UI-021 — toggling grouping OFF restores the flat poster grid with the same series', async () => {
    renderGrouped();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(3),
    );
    await toggleGrouping(user);
    await waitFor(() =>
      expect(screen.getByTestId('franchise-group')).toBeInTheDocument(),
    );

    await toggleGrouping(user);
    expect(screen.getByTestId('library-poster-grid')).toBeInTheDocument();
    expect(screen.queryByTestId('franchise-group')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('series-card')).toHaveLength(3);
    expect(screen.getByText('Batman (2011)')).toBeInTheDocument();
    expect(screen.getByText('Saga')).toBeInTheDocument();
  });

  it('FRG-UI-021 — a projection-multi-run franchise stays a stacked card even if only one run is cached', async () => {
    const partialSeries: SeriesResource[] = [
      makeSeriesResource({
        id: 1,
        title: 'Batman (2011)',
        sort_title: 'batman (2011)',
        start_year: 2011,
        series_group_id: 1,
      }),
    ];
    renderGrouped(partialSeries, [GROUPED_GROUPS[0]]);
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(1),
    );
    await toggleGrouping(user);

    await waitFor(() =>
      expect(screen.getByTestId('franchise-group')).toBeInTheDocument(),
    );
    const stack = screen.getByTestId('franchise-group');
    expect(within(stack).getByText('Batman')).toBeInTheDocument();
    expect(within(stack).getByText('30 / 50')).toBeInTheDocument();
    expect(within(stack).getByText(/2 vols/)).toBeInTheDocument();
    // No ordinary single card is rendered — the franchise did NOT collapse to one.
    expect(screen.queryAllByTestId('series-card')).toHaveLength(0);
  });

  it('FRG-UI-021 — grouping is display-only: per-series navigation still works from a nested run', async () => {
    renderGrouped();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(3),
    );
    await user.click(screen.getByRole('button', { name: 'Table' }));
    await toggleGrouping(user);
    await waitFor(() =>
      expect(screen.getByTestId('franchise-group')).toBeInTheDocument(),
    );

    const group = screen.getByTestId('franchise-group');
    await user.click(within(group).getAllByTestId('series-row')[0]);
    expect(screen.getByTestId('detail-stub')).toBeInTheDocument();
  });

  it('FRG-UI-021 — the group rename affordance fires the group-edit mutation with the rename op (FRG-SER-017)', async () => {
    const { spy } = renderGrouped();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(3),
    );
    await user.click(screen.getByRole('button', { name: 'Table' }));
    await toggleGrouping(user);
    await waitFor(() =>
      expect(screen.getByTestId('franchise-group')).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId('franchise-group-menu'));
    const input = screen.getByTestId('franchise-rename-input');
    await user.clear(input);
    await user.type(input, 'The Dark Knight');
    await user.click(screen.getByTestId('franchise-rename-submit'));

    // PUT /api/v1/series/1 (the first sorted run) carrying only the rename op.
    await waitFor(() => {
      const putCall = spy.mock.calls.find(
        ([path, init]) => init?.method === 'PUT' && path === '/api/v1/series/1',
      );
      expect(putCall).toBeDefined();
      expect(putCall?.[1]?.body).toEqual({
        group: { action: 'rename', title: 'The Dark Knight' },
      });
    });
  });

  it('FRG-UI-021 — the detach affordance reassigns a run out of the group (FRG-SER-017)', async () => {
    const { spy } = renderGrouped();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(3),
    );
    await user.click(screen.getByRole('button', { name: 'Table' }));
    await toggleGrouping(user);
    await waitFor(() =>
      expect(screen.getByTestId('franchise-group')).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId('franchise-group-menu'));
    await user.click(screen.getByTestId('franchise-detach-2'));

    await waitFor(() => {
      const putCall = spy.mock.calls.find(
        ([path, init]) => init?.method === 'PUT' && path === '/api/v1/series/2',
      );
      expect(putCall).toBeDefined();
      expect(putCall?.[1]?.body).toEqual({ group: { action: 'detach' } });
    });
  });

  it('FRG-UI-021 — the franchise actions menu closes on Escape and on an outside click', async () => {
    renderGrouped();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(3),
    );
    await toggleGrouping(user);
    await waitFor(() =>
      expect(screen.getByTestId('franchise-group')).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId('franchise-group-menu'));
    expect(screen.getByTestId('franchise-menu')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByTestId('franchise-menu')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('franchise-group-menu'));
    expect(screen.getByTestId('franchise-menu')).toBeInTheDocument();
    await user.click(screen.getByTestId('library-count-line'));
    expect(screen.queryByTestId('franchise-menu')).not.toBeInTheDocument();
  });
});

/**
 * FRG-UI-022 — Collected-edition (trade) surfacing: the book-type badge on the
 * poster card and the nested franchise run, plus the display-only editions
 * filter (now in the Filter menu). A null book-type carries no badge; the filter
 * partitions the shown series without touching identity, navigation, or
 * monitoring.
 */

const TYPED_SERIES: SeriesResource[] = [
  makeSeriesResource({ id: 1, title: 'Saga', sort_title: 'saga', booktype: null }),
  makeSeriesResource({ id: 2, title: 'Watchmen', sort_title: 'watchmen', booktype: 'tpb' }),
  makeSeriesResource({ id: 3, title: 'Black Hole', sort_title: 'black hole', booktype: 'gn' }),
  makeSeriesResource({ id: 4, title: 'Bone', sort_title: 'bone', booktype: null }),
];

describe('FRG-UI-022: collected-edition surfacing', () => {
  it('FRG-UI-022 — a typed series shows a book-type badge in the grid while a null-typed run shows none', async () => {
    renderLibrary(TYPED_SERIES);

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(4),
    );

    const cardFor = (title: string) =>
      screen
        .getAllByTestId('series-card')
        .find((c) => within(c).queryByTitle(title)) as HTMLElement;

    expect(within(cardFor('Watchmen')).getByTestId('booktype-badge')).toHaveTextContent(
      'TPB',
    );
    expect(within(cardFor('Black Hole')).getByTestId('booktype-badge')).toHaveTextContent(
      'GN',
    );
    expect(within(cardFor('Saga')).queryByTestId('booktype-badge')).toBeNull();
    expect(within(cardFor('Bone')).queryByTestId('booktype-badge')).toBeNull();
  });

  it('FRG-UI-022 — the badge also renders on a nested franchise run (grouped row context)', async () => {
    const groupedTyped: SeriesResource[] = [
      makeSeriesResource({
        id: 1,
        title: 'Batman (2011)',
        sort_title: 'batman (2011)',
        start_year: 2011,
        series_group_id: 1,
        booktype: 'hc',
      }),
      makeSeriesResource({
        id: 2,
        title: 'Batman (2016)',
        sort_title: 'batman (2016)',
        start_year: 2016,
        series_group_id: 1,
        booktype: null,
      }),
    ];
    renderGrouped(groupedTyped, [GROUPED_GROUPS[0]]);
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(2),
    );
    await user.click(screen.getByRole('button', { name: 'Table' }));
    await toggleGrouping(user);
    await waitFor(() =>
      expect(screen.getByTestId('franchise-group')).toBeInTheDocument(),
    );

    // Exactly one member run (the HC one) carries a badge inside the group.
    const group = screen.getByTestId('franchise-group');
    const badges = within(group).getAllByTestId('booktype-badge');
    expect(badges).toHaveLength(1);
    expect(badges[0]).toHaveTextContent('HC');
  });

  it('FRG-UI-022 — the editions filter partitions the shown series without changing navigation', async () => {
    renderLibrary(TYPED_SERIES);
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(4),
    );

    // Pick the card-title element (not the badge's "Collected edition:" title).
    const shownTitles = () =>
      screen
        .getAllByTestId('series-card')
        .map(
          (c) =>
            within(c)
              .getAllByTitle(/.+/)
              .find((el) => !el.getAttribute('title')?.startsWith('Collected edition'))
              ?.textContent,
        );

    await pickFilter(user, 'edition-filter-collected');
    expect(screen.getAllByTestId('series-card')).toHaveLength(2);
    expect(shownTitles()).toEqual(['Black Hole', 'Watchmen']);

    await pickFilter(user, 'edition-filter-singles');
    expect(screen.getAllByTestId('series-card')).toHaveLength(2);
    expect(shownTitles()).toEqual(['Bone', 'Saga']);

    // Navigation from a filtered card is unchanged (display-only).
    await user.click(
      screen
        .getAllByTestId('series-card')
        .find((c) => within(c).queryByTitle('Bone')) as HTMLElement,
    );
    expect(screen.getByTestId('detail-stub')).toBeInTheDocument();
  });

  it('FRG-UI-022 — the editions filter partitions nested runs inside the grouped view too', async () => {
    const groupedTyped: SeriesResource[] = [
      makeSeriesResource({
        id: 1,
        title: 'Batman (2011)',
        sort_title: 'batman (2011)',
        start_year: 2011,
        series_group_id: 1,
        booktype: 'tpb',
      }),
      makeSeriesResource({
        id: 2,
        title: 'Batman (2016)',
        sort_title: 'batman (2016)',
        start_year: 2016,
        series_group_id: 1,
        booktype: null,
      }),
    ];
    renderGrouped(groupedTyped, [GROUPED_GROUPS[0]]);
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(2),
    );
    await user.click(screen.getByRole('button', { name: 'Table' }));
    await toggleGrouping(user);
    await waitFor(() =>
      expect(screen.getByTestId('franchise-group')).toBeInTheDocument(),
    );
    expect(screen.getAllByTestId('series-row')).toHaveLength(2);

    // Collected only → only the TPB run survives inside the franchise.
    await pickFilter(user, 'edition-filter-collected');
    expect(screen.getAllByTestId('series-row')).toHaveLength(1);
    expect(screen.getByText('Batman (2011)')).toBeInTheDocument();
  });
});
