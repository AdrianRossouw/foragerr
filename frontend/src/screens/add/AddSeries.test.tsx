import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import {
  makeCommand,
  mockFormatProfiles,
  mockLookupCandidates,
  mockRootFolders,
  mockSeriesCreated,
  pageOf,
} from '../../test/mockData';
import { useUiStore } from '../../store/uiStore';
import { AddSeries, normalizeLookupTerm } from './AddSeries';
import { SeriesDetail } from '../series/SeriesDetail';

/**
 * FRG-UI-005 — Add-series screen: ComicVine lookup with plausibility
 * annotations, add-options panel, add -> navigate to detail with the queued
 * refresh command visible in progress. Fake fetcher only.
 */

beforeEach(() => {
  useUiStore.setState({ interactiveSearchIssueId: null });
});

function addFetcher() {
  return fakeFetcher((path, options) => {
    const method = options?.method ?? 'GET';
    if (method === 'GET' && path === '/api/v1/series/lookup?term=saga') {
      return mockLookupCandidates;
    }
    if (method === 'GET' && path.startsWith('/api/v1/series/lookup?term=')) {
      return [];
    }
    if (method === 'GET' && path === '/api/v1/rootfolder') return mockRootFolders;
    if (method === 'GET' && path === '/api/v1/formatprofile') {
      return mockFormatProfiles;
    }
    if (method === 'POST' && path === '/api/v1/series') return mockSeriesCreated;
    // Routes the detail screen needs after the add navigates to it:
    if (method === 'GET' && path === '/api/v1/series/42') return mockSeriesCreated;
    if (method === 'GET' && path.startsWith('/api/v1/issues?seriesId=42')) {
      return pageOf([]);
    }
    if (method === 'GET' && path === '/api/v1/command/55') {
      return makeCommand({ id: 55, name: 'refresh-series', status: 'started' });
    }
    throw new Error(`unexpected request: ${method} ${path}`);
  });
}

function renderAdd() {
  const { spy, fetcher } = addFetcher();
  const utils = renderWithProviders(
    <Routes>
      <Route path="/add" element={<AddSeries />} />
      <Route path="/series/:id" element={<SeriesDetail />} />
    </Routes>,
    { fetcher, route: '/add' },
  );
  return { spy, ...utils };
}

async function searchFor(term: string) {
  const user = userEvent.setup();
  await user.type(screen.getByRole('searchbox', { name: 'Search ComicVine' }), term);
  await user.click(screen.getByRole('button', { name: 'Search' }));
  return user;
}

describe('FRG-UI-005: add series', () => {
  it('FRG-UI-005 — search renders ComicVine candidates with plausibility annotations', async () => {
    const { spy } = renderAdd();
    await searchFor('saga');

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series/lookup?term=saga'),
    );

    // Strong candidate: poster, year, publisher and its plausibility chips.
    const strong = screen.getByTestId('candidate-40501234');
    expect(within(strong).getByText('Saga')).toBeInTheDocument();
    expect(within(strong).getByText('(2012)')).toBeInTheDocument();
    expect(within(strong).getByText('Image')).toBeInTheDocument();
    expect(within(strong).getByText('63 issues')).toBeInTheDocument();
    expect(within(strong).getByText('Name match 100%')).toBeInTheDocument();
    expect(within(strong).getByText('Year match')).toBeInTheDocument();
    expect(within(strong).getByText('Target issue plausible')).toBeInTheDocument();

    // Weak candidate: annotations rendered honestly, plus library membership.
    // Its count_of_issues is null -> the issue-count annotation is OMITTED.
    const weak = screen.getByTestId('candidate-40509999');
    expect(within(weak).getByText('Name match 42%')).toBeInTheDocument();
    expect(within(weak).getByText('Year ±30')).toBeInTheDocument();
    expect(within(weak).getByText('Target issue unlikely')).toBeInTheDocument();
    expect(within(weak).getByText('In library')).toBeInTheDocument();
    expect(within(weak).queryByText(/\d+ issues?/)).not.toBeInTheDocument();
  });

  it('FRG-UI-005 — selecting a candidate exposes root folder, format profile, monitor strategy and search-on-add controls', async () => {
    renderAdd();
    const user = await searchFor('saga');

    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Select Saga' }));

    const panel = screen.getByTestId('add-options-panel');

    // Root folders from GET /api/v1/rootfolder: path + formatted free space
    // (omitted when free_space is null), defaulting to the first entry.
    const rootFolder = within(panel).getByRole('combobox', { name: 'Root folder' });
    await waitFor(() =>
      expect(within(rootFolder).getAllByRole('option')).toHaveLength(2),
    );
    expect(
      within(rootFolder).getByRole('option', { name: '/comics — 232.8 GB free' }),
    ).toBeInTheDocument();
    expect(
      within(rootFolder).getByRole('option', { name: '/mnt/archive/comics' }),
    ).toBeInTheDocument();
    expect(rootFolder).toHaveValue('1');

    // Format profiles from GET /api/v1/formatprofile: name per option,
    // defaulting to the first (seeded) profile.
    const profile = within(panel).getByRole('combobox', { name: 'Format profile' });
    expect(
      within(profile).getByRole('option', { name: 'Standard' }),
    ).toBeInTheDocument();
    expect(
      within(profile).getByRole('option', { name: 'CBZ Only' }),
    ).toBeInTheDocument();
    expect(profile).toHaveValue('1');

    expect(within(panel).getByRole('combobox', { name: 'Monitor strategy' })).toBeInTheDocument();
    expect(
      within(panel).getByRole('checkbox', { name: 'Start search for missing issues' }),
    ).toBeInTheDocument();
  });

  it('FRG-UI-005 — confirming the add posts the payload, navigates to detail, and the refresh command is visible in progress', async () => {
    const { spy } = renderAdd();
    const user = await searchFor('saga');

    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Select Saga' }));

    const panel = screen.getByTestId('add-options-panel');
    const rootFolder = within(panel).getByRole('combobox', { name: 'Root folder' });
    await waitFor(() =>
      expect(within(rootFolder).getAllByRole('option')).toHaveLength(2),
    );
    // Pick NON-default entries so the POST proves the chosen ids travel.
    await user.selectOptions(rootFolder, '2');
    await user.selectOptions(
      within(panel).getByRole('combobox', { name: 'Format profile' }),
      '2',
    );
    await user.selectOptions(
      within(panel).getByRole('combobox', { name: 'Monitor strategy' }),
      'missing',
    );
    await user.click(
      within(panel).getByRole('checkbox', { name: 'Start search for missing issues' }),
    );
    await user.click(within(panel).getByRole('button', { name: 'Add Saga' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series', {
        method: 'POST',
        body: {
          cv_volume_id: 40501234,
          root_folder_id: 2,
          format_profile_id: 2,
          monitor_strategy: 'missing',
          monitor_new_items: 'all',
          search_on_add: true,
        },
      }),
    );

    // Navigated to the new series' detail route...
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Saga' })).toBeInTheDocument(),
    );
    // ...with the queued refresh command rendered live and in progress.
    await waitFor(() =>
      expect(screen.getByTestId('command-status')).toHaveTextContent(
        'Refresh: started',
      ),
    );
  });

  it('FRG-UI-005 — a pasted ComicVine volume URL or cv: id normalizes to the bare 4050 id term', async () => {
    expect(normalizeLookupTerm('https://comicvine.gamespot.com/saga/4050-56789/')).toBe(
      '4050-56789',
    );
    expect(normalizeLookupTerm('cv:4050-123')).toBe('4050-123');
    expect(normalizeLookupTerm('  Saga  ')).toBe('Saga');

    const { spy } = renderAdd();
    await searchFor('https://comicvine.gamespot.com/saga/4050-56789/');
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series/lookup?term=4050-56789'),
    );
  });
});
