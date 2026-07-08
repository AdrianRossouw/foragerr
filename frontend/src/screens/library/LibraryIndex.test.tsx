import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import {
  makeGroupMember,
  makeMockLibrary,
  makeSeriesGroup,
  makeSeriesResource,
  pageOf,
} from '../../test/mockData';
import { useUiStore } from '../../store/uiStore';
import type { FetcherInit } from '../../api/fetcher';
import type { SeriesGroupResource, SeriesResource } from '../../api/types';
import { LibraryIndex } from './LibraryIndex';

/**
 * FRG-UI-003 — Library index screen: poster grid / table toggle, toolbar sort
 * + text filter, local covers, navigation to detail. All data rides the fake
 * fetcher; no live backend.
 */

beforeEach(() => {
  useUiStore.setState({
    libraryViewMode: 'poster',
    librarySortKey: 'title',
    libraryGroupByFranchise: false,
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
    </Routes>,
    { fetcher },
  );
  return { spy, ...utils };
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
    expect(within(firstCard).getByText(/Monitored|Unmonitored/)).toBeInTheDocument();
    expect(within(firstCard).getByRole('status')).toBeInTheDocument();

    // Every poster img points at the local cover endpoint — never an
    // external ComicVine image host.
    const images = grid.querySelectorAll('img');
    expect(images.length).toBe(55);
    for (const img of images) {
      expect(img.getAttribute('src')).toMatch(/^\/api\/v1\/series\/\d+\/cover$/);
    }
  });

  it('FRG-UI-003 — view toggle switches poster grid to table rows and back', async () => {
    renderLibrary(makeMockLibrary(5));
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getByTestId('library-poster-grid')).toBeInTheDocument(),
    );

    await user.click(screen.getByRole('button', { name: 'Table' }));
    const table = screen.getByTestId('library-table');
    expect(screen.getAllByTestId('series-row')).toHaveLength(5);
    expect(within(table).getByText('Title')).toBeInTheDocument();
    expect(within(table).getByText('Issues')).toBeInTheDocument();
    expect(screen.queryByTestId('library-poster-grid')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Posters' }));
    expect(screen.getByTestId('library-poster-grid')).toBeInTheDocument();
    expect(screen.queryByTestId('library-table')).not.toBeInTheDocument();
  });

  it('FRG-UI-003 — toolbar sorts by title and filters by title substring', async () => {
    const records = [
      makeSeriesResource({ id: 1, title: 'Saga', sort_title: 'saga' }),
      makeSeriesResource({ id: 2, title: 'Bone', sort_title: 'bone' }),
      makeSeriesResource({ id: 3, title: 'Alpha Flight', sort_title: 'alpha flight' }),
    ];
    renderLibrary(records);
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getAllByTestId('series-card')).toHaveLength(3));

    // Default title sort: alphabetic by sort_title.
    const titles = () =>
      screen
        .getAllByTestId('series-card')
        .map((card) => within(card).getByTitle(/.+/).textContent);
    expect(titles()).toEqual(['Alpha Flight', 'Bone', 'Saga']);

    await user.type(screen.getByLabelText('Filter series'), 'sa');
    expect(titles()).toEqual(['Saga']);
  });

  it('FRG-UI-003 — toolbar sort by date added orders newest first', async () => {
    const records = [
      makeSeriesResource({
        id: 1,
        title: 'Saga',
        sort_title: 'saga',
        added_at: '2026-03-01T00:00:00Z',
      }),
      makeSeriesResource({
        id: 2,
        title: 'Bone',
        sort_title: 'bone',
        added_at: '2026-05-01T00:00:00Z',
      }),
      makeSeriesResource({
        id: 3,
        title: 'Alpha Flight',
        sort_title: 'alpha flight',
        added_at: '2026-04-01T00:00:00Z',
      }),
    ];
    renderLibrary(records);
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getAllByTestId('series-card')).toHaveLength(3));
    await user.selectOptions(screen.getByLabelText('Sort'), 'added');

    const titles = screen
      .getAllByTestId('series-card')
      .map((card) => within(card).getByTitle(/.+/).textContent);
    expect(titles).toEqual(['Bone', 'Alpha Flight', 'Saga']);
  });

  it('FRG-UI-003 — clicking a series card navigates to its detail route', async () => {
    renderLibrary([makeSeriesResource({ id: 9, title: 'Saga', sort_title: 'saga' })]);
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByTestId('series-card')).toBeInTheDocument());
    await user.click(screen.getByTestId('series-card'));
    expect(screen.getByTestId('detail-stub')).toBeInTheDocument();
  });
});

/**
 * FRG-UI-021 — Grouped (franchise) library view: multi-run franchises nest
 * under collapsible headers with a roll-up stat; single-run franchises render
 * as ordinary rows; per-series navigation/actions are unchanged; and the group
 * rename/reassign affordance fires the group-edit mutation (FRG-SER-017). All
 * data rides the fake fetcher.
 */

// Two runs of one title (grouped) + one ungrouped singleton franchise.
const GROUPED_SERIES: SeriesResource[] = [
  makeSeriesResource({
    id: 1,
    title: 'Batman (2011)',
    sort_title: 'batman (2011)',
    series_group_id: 1,
  }),
  makeSeriesResource({
    id: 2,
    title: 'Batman (2016)',
    sort_title: 'batman (2016)',
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
    series: [makeGroupMember({ id: 1 }), makeGroupMember({ id: 2 })],
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
      // Echo a plausible updated resource so the mutation resolves.
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
  it('FRG-UI-021 — grouped mode nests multiple runs under one collapsible franchise header; single-run franchises stay ordinary rows', async () => {
    renderGrouped();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(3),
    );

    // Turn grouping on.
    await user.click(screen.getByTestId('group-by-toggle'));

    // Exactly one franchise group (Batman is the only multi-run title); Saga is
    // a single-run franchise rendered as an ordinary card with no group chrome.
    await waitFor(() =>
      expect(screen.getAllByTestId('franchise-group')).toHaveLength(1),
    );
    const group = screen.getByTestId('franchise-group');
    const header = within(group).getByTestId('franchise-group-header');
    expect(within(header).getByText('Batman')).toBeInTheDocument();
    // Roll-up stat comes straight from the projection: owned/issue + run count.
    expect(within(header).getByText('30/50')).toBeInTheDocument();
    expect(within(header).getByText('2 runs')).toBeInTheDocument();

    // The two runs are nested inside the franchise; Saga is not.
    expect(within(group).getAllByTestId('series-card')).toHaveLength(2);
    expect(within(group).queryByText('Saga')).not.toBeInTheDocument();
    expect(screen.getByText('Saga')).toBeInTheDocument();
    expect(screen.getAllByTestId('series-card')).toHaveLength(3);

    // Collapsible: collapsing the header hides the member runs.
    await user.click(within(header).getByTestId('franchise-collapse'));
    expect(screen.queryByTestId('franchise-members')).not.toBeInTheDocument();
    // Saga (single-run) stays visible regardless of the group's collapse state.
    expect(screen.getByText('Saga')).toBeInTheDocument();
  });

  it('FRG-UI-021 — toggling grouping OFF restores the flat list with the same series rows', async () => {
    renderGrouped();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(3),
    );

    await user.click(screen.getByTestId('group-by-toggle'));
    await waitFor(() =>
      expect(screen.getByTestId('franchise-group')).toBeInTheDocument(),
    );

    // Toggle back off: flat poster grid, same three series, no group chrome.
    await user.click(screen.getByTestId('group-by-toggle'));
    expect(screen.getByTestId('library-poster-grid')).toBeInTheDocument();
    expect(screen.queryByTestId('franchise-group')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('series-card')).toHaveLength(3);
    expect(screen.getByText('Batman (2011)')).toBeInTheDocument();
    expect(screen.getByText('Saga')).toBeInTheDocument();
  });

  it('FRG-UI-021 — per-series navigation still works from a member run in grouped mode', async () => {
    renderGrouped();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(3),
    );
    await user.click(screen.getByTestId('group-by-toggle'));
    await waitFor(() =>
      expect(screen.getByTestId('franchise-group')).toBeInTheDocument(),
    );

    const group = screen.getByTestId('franchise-group');
    // Click the first nested run; it navigates to its detail route unchanged.
    await user.click(within(group).getAllByTestId('series-card')[0]);
    expect(screen.getByTestId('detail-stub')).toBeInTheDocument();
  });

  it('FRG-UI-021 — group rename affordance fires the group-edit mutation with the rename op (FRG-SER-017)', async () => {
    const { spy } = renderGrouped();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(3),
    );
    await user.click(screen.getByTestId('group-by-toggle'));
    await waitFor(() =>
      expect(screen.getByTestId('franchise-group')).toBeInTheDocument(),
    );

    // Open the header menu, rename the franchise, submit.
    await user.click(screen.getByTestId('franchise-group-menu'));
    const input = screen.getByTestId('franchise-rename-input');
    await user.clear(input);
    await user.type(input, 'The Dark Knight');
    await user.click(screen.getByTestId('franchise-rename-submit'));

    // PUT /api/v1/series/{firstMemberId} carrying only the rename op — the
    // group is renamed via any member series (id 1, the first sorted run).
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

  it('FRG-UI-021 — detach affordance reassigns a run out of the group (FRG-SER-017)', async () => {
    const { spy } = renderGrouped();
    const user = userEvent.setup();

    await waitFor(() =>
      expect(screen.getAllByTestId('series-card')).toHaveLength(3),
    );
    await user.click(screen.getByTestId('group-by-toggle'));
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
});
