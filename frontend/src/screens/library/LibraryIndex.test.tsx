import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { makeMockLibrary, makeSeriesResource, pageOf } from '../../test/mockData';
import { useUiStore } from '../../store/uiStore';
import type { SeriesResource } from '../../api/types';
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
