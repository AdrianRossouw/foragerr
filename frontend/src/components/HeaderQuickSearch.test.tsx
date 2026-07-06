import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes, useLocation, useParams } from 'react-router-dom';
import { renderWithProviders } from '../test/renderWithProviders';
import { fakeFetcher } from '../test/fakeFetcher';
import { makeSeriesResource, pageOf } from '../test/mockData';
import type { SeriesResource, AddSeriesNavigationState } from '../api/types';
import { HeaderQuickSearch } from './HeaderQuickSearch';

function DetailStub() {
  const { id } = useParams();
  return <div data-testid="detail-stub">series {id}</div>;
}

function AddStub() {
  const location = useLocation();
  const state = location.state as AddSeriesNavigationState | null;
  return <div data-testid="add-stub">{state?.prefillTerm ?? ''}</div>;
}

const SERIES: SeriesResource[] = [
  makeSeriesResource({ id: 1, title: 'Saga', sort_title: 'saga', aliases: [] }),
  makeSeriesResource({
    id: 2,
    title: 'Invincible',
    sort_title: 'invincible',
    aliases: ['The Invincible Man'],
  }),
];

/** `series: null` simulates the ['series'] index never resolving (loading). */
function renderHeader(series: SeriesResource[] | null = SERIES) {
  const { spy, fetcher } = fakeFetcher((path) => {
    if (path.startsWith('/api/v1/series?')) {
      if (series === null) return new Promise(() => {});
      return pageOf(series, { totalRecords: series.length });
    }
    throw new Error(`unexpected request: ${path}`);
  });
  const utils = renderWithProviders(
    <Routes>
      <Route path="/" element={<HeaderQuickSearch />} />
      <Route path="/series/:id" element={<DetailStub />} />
      <Route path="/add" element={<AddStub />} />
    </Routes>,
    { fetcher, route: '/' },
  );
  return { spy, ...utils };
}

const searchbox = () => screen.getByRole('searchbox', { name: 'Quick search your library' });

/**
 * FRG-UI-019 — the global header quick-search: client-only fuzzy match over
 * the already-cached ['series'] index (titles + aliases), keyboard
 * navigation, the always-present ComicVine fall-through carrying the term
 * into Add Series, and graceful degradation of an empty/loading cache.
 */
describe('FRG-UI-019: header quick search', () => {
  it('FRG-UI-019 — matches local titles AND aliases, issuing no network request per keystroke', async () => {
    const { spy } = renderHeader();
    const user = userEvent.setup();

    await user.type(searchbox(), 'invincible man');
    await waitFor(() => expect(screen.getByTestId('quick-result-2')).toBeInTheDocument());

    const callsAfterMatch = spy.mock.calls.length;
    await user.type(searchbox(), ' extra');
    expect(spy.mock.calls.length).toBe(callsAfterMatch);
  });

  it('FRG-UI-019 — arrow keys move the active result, Enter navigates to it, and Escape closes without navigating', async () => {
    renderHeader();
    const user = userEvent.setup();

    await user.type(searchbox(), 'sag');
    await waitFor(() => expect(screen.getByTestId('quick-result-1')).toBeInTheDocument());

    // Escape closes the list; no navigation happens.
    await user.keyboard('{Escape}');
    expect(screen.queryByTestId('quick-result-1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('detail-stub')).not.toBeInTheDocument();

    // Typing again reopens it; row 0 is the Saga match, row 1 the fall-through.
    await user.type(searchbox(), 'a');
    await waitFor(() => expect(screen.getByTestId('quick-result-1')).toBeInTheDocument());
    await user.keyboard('{Enter}');
    await waitFor(() => expect(screen.getByTestId('detail-stub')).toHaveTextContent('series 1'));
  });

  it('FRG-UI-019 — the ComicVine fall-through is always present (even with local matches) and carries the term into Add Series', async () => {
    renderHeader();
    const user = userEvent.setup();

    await user.type(searchbox(), 'saga');
    await waitFor(() => expect(screen.getByTestId('quick-result-1')).toBeInTheDocument());

    const fallThrough = screen.getByTestId('quick-result-fallthrough');
    expect(fallThrough).toHaveTextContent('Search ComicVine for “saga”…');

    await user.click(fallThrough);
    await waitFor(() => expect(screen.getByTestId('add-stub')).toHaveTextContent('saga'));
  });

  it('FRG-UI-019 — an empty or still-loading cache degrades to only the fall-through row', async () => {
    renderHeader(null);
    const user = userEvent.setup();

    await user.type(searchbox(), 'anything');
    await waitFor(() =>
      expect(screen.getByTestId('quick-result-fallthrough')).toBeInTheDocument(),
    );
    expect(screen.getAllByRole('option')).toHaveLength(1);
  });

  it('FRG-UI-019 — a click outside the widget closes the results list but keeps the typed term', async () => {
    renderHeader();
    const user = userEvent.setup();

    await user.type(searchbox(), 'saga');
    await waitFor(() =>
      expect(screen.getByRole('listbox')).toBeInTheDocument(),
    );

    // A pointer-down elsewhere in the document dismisses the open listbox...
    await user.click(document.body);
    await waitFor(() =>
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument(),
    );
    // ...without clearing the term (dismissal, not a reset — Escape semantics).
    expect(searchbox()).toHaveValue('saga');
  });
});
