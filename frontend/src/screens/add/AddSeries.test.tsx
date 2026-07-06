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
import { ApiRequestError, isComicVineAuthError } from '../../api/fetcher';
import { AddSeries, normalizeLookupTerm } from './AddSeries';
import { SeriesDetail } from '../series/SeriesDetail';

/**
 * The backend's verbatim ComicVine auth-failure error body (pinned by a
 * backend contract test). The errors[] entry naming the offending field is
 * the machine-readable discriminator the screen classifies on — the message
 * text is presentation only.
 */
const CV_AUTH_BODY = {
  message:
    'comicvine lookup failed: ComicVine rejected the API key (missing or invalid) — set comicvine_api_key',
  errors: [
    {
      field: 'comicvine_api_key',
      message:
        'ComicVine rejected the API key (missing or invalid) — set comicvine_api_key',
    },
  ],
};

/** A non-credential lookup failure: uniform body, no field discriminator. */
const CV_UPSTREAM_BODY = {
  message: 'comicvine lookup failed: upstream unavailable',
  errors: [],
};

function cvAuthError(): ApiRequestError {
  return new ApiRequestError(503, CV_AUTH_BODY, '/api/v1/series/lookup?term=saga');
}

function cvUpstreamError(): ApiRequestError {
  return new ApiRequestError(
    503,
    CV_UPSTREAM_BODY,
    '/api/v1/series/lookup?term=saga',
  );
}

/**
 * FRG-UI-005 — Add-series screen: ComicVine lookup with plausibility
 * annotations, distinct non-success outcome states, add-options panel,
 * add -> navigate to detail with the queued refresh command visible in
 * progress. Fake fetcher only.
 */

beforeEach(() => {
  useUiStore.setState({ interactiveSearchIssueId: null });
});

/** Default lookup resolver: candidates for `saga`, clean-empty otherwise. */
function defaultLookup(path: string): unknown {
  if (path === '/api/v1/series/lookup?term=saga') {
    return { records: mockLookupCandidates, complete: true, truncated: false };
  }
  return { records: [], complete: true, truncated: false };
}

function addFetcher({
  lookup = defaultLookup,
}: { lookup?: (path: string) => unknown } = {}) {
  return fakeFetcher((path, options) => {
    const method = options?.method ?? 'GET';
    if (method === 'GET' && path.startsWith('/api/v1/series/lookup?term=')) {
      return lookup(path);
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

function renderAdd(overrides: { lookup?: (path: string) => unknown } = {}) {
  const { spy, fetcher } = addFetcher(overrides);
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

/**
 * FRG-UI-005 — the non-success search outcomes must render distinctly and
 * mutually exclusively: a credential error, a generic lookup error, a
 * degraded walk (with and without records), a capped result set, and a
 * genuinely empty result. A credential failure or degraded walk is NEVER
 * shown as plain "no results", and stale candidates never render under an
 * error.
 */
describe('FRG-UI-005: lookup outcome states', () => {
  it('FRG-UI-005 — a ComicVine credential failure renders Settings guidance, not the empty state', async () => {
    renderAdd({
      lookup: () => {
        throw cvAuthError();
      },
    });
    await searchFor('saga');

    await waitFor(() =>
      expect(
        screen.getByText('ComicVine API key missing or invalid — check Settings.'),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
    // The credential error must NOT be dressed up as "no results".
    expect(screen.queryByText(/No volumes found/)).not.toBeInTheDocument();
    // ...nor as the generic retry error.
    expect(screen.queryByText(/Try again in a moment/)).not.toBeInTheDocument();
  });

  it('FRG-UI-005 — credential detection is structural (errors[] field), not message prose', () => {
    // The field discriminator decides, regardless of the message text.
    expect(isComicVineAuthError(cvAuthError())).toBe(true);
    expect(
      isComicVineAuthError(
        new ApiRequestError(
          503,
          { message: 'anything at all', errors: CV_AUTH_BODY.errors },
          '/api/v1/series/lookup?term=saga',
        ),
      ),
    ).toBe(true);
    // Credential-sounding prose WITHOUT the field must not match.
    expect(
      isComicVineAuthError(
        new ApiRequestError(
          503,
          { message: CV_AUTH_BODY.message, errors: [] },
          '/api/v1/series/lookup?term=saga',
        ),
      ),
    ).toBe(false);
    // Non-ApiRequestError values and missing bodies never match.
    expect(isComicVineAuthError(new Error(CV_AUTH_BODY.message))).toBe(false);
    expect(
      isComicVineAuthError(
        new ApiRequestError(503, null, '/api/v1/series/lookup?term=saga'),
      ),
    ).toBe(false);
    expect(isComicVineAuthError(undefined)).toBe(false);
  });

  it('FRG-UI-005 — a non-credential lookup failure renders the generic error', async () => {
    renderAdd({
      lookup: () => {
        throw cvUpstreamError();
      },
    });
    await searchFor('saga');

    await waitFor(() =>
      expect(
        screen.getByText('ComicVine lookup failed. Try again in a moment.'),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText(/check Settings/)).not.toBeInTheDocument();
  });

  it('FRG-UI-005 — a degraded walk with zero records renders as a lookup failure, not a footnote', async () => {
    renderAdd({
      lookup: () => ({ records: [], complete: false, truncated: false }),
    });
    await searchFor('saga');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(
      'ComicVine lookup failed part-way and returned nothing — try again in a moment.',
    );
    // Error styling and retry guidance — never "no results" or a mild notice.
    expect(screen.queryByText(/No volumes found/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Results may be incomplete/)).not.toBeInTheDocument();
  });

  it('FRG-UI-005 — a capped result renders the candidates plus narrow-the-term guidance', async () => {
    renderAdd({
      lookup: () => ({
        records: mockLookupCandidates,
        complete: false,
        truncated: true,
      }),
    });
    await searchFor('saga');

    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    expect(screen.getByRole('status')).toHaveTextContent(
      'Too many results — ComicVine capped this search. Narrow the term.',
    );
    // The cap advises narrowing — never the transient "retry" wording.
    expect(screen.queryByText(/Results may be incomplete/)).not.toBeInTheDocument();
    expect(screen.queryByText(/try again/i)).not.toBeInTheDocument();
  });

  it('FRG-UI-005 — an incomplete result renders the candidates plus an incomplete notice', async () => {
    renderAdd({
      lookup: () => ({
        records: mockLookupCandidates,
        complete: false,
        truncated: false,
      }),
    });
    await searchFor('saga');

    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    expect(screen.getByRole('status')).toHaveTextContent(
      'Results may be incomplete — ComicVine did not return everything.',
    );
    // Incomplete is NOT "no results" and NOT the cap notice.
    expect(screen.queryByText(/No volumes found/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Too many results/)).not.toBeInTheDocument();
  });

  it('FRG-UI-005 — a complete-and-empty result renders the plain "No volumes found" state', async () => {
    renderAdd({
      lookup: () => ({ records: [], complete: true, truncated: false }),
    });
    await searchFor('saga');

    await waitFor(() =>
      expect(screen.getByText(/No volumes found/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Results may be incomplete/)).not.toBeInTheDocument();
    expect(screen.queryByText(/check Settings/)).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('FRG-UI-005 — re-submitting the same term after an error refires the lookup for real', async () => {
    let calls = 0;
    const { spy } = renderAdd({
      lookup: () => {
        calls += 1;
        if (calls === 1) throw cvUpstreamError();
        return { records: mockLookupCandidates, complete: true, truncated: false };
      },
    });
    const user = await searchFor('saga');

    await waitFor(() =>
      expect(
        screen.getByText('ComicVine lookup failed. Try again in a moment.'),
      ).toBeInTheDocument(),
    );

    // Same term, submitted again: a FRESH request must be issued — the error
    // is not served from cache and no term perturbation is needed.
    await user.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    const lookupCalls = spy.mock.calls.filter(
      ([path]) => path === '/api/v1/series/lookup?term=saga',
    );
    expect(lookupCalls).toHaveLength(2);
    expect(
      screen.queryByText(/Try again in a moment/),
    ).not.toBeInTheDocument();
  });

  it('FRG-UI-005 — a same-term retry of a degraded outcome refetches, and an error then suppresses the stale candidates', async () => {
    let calls = 0;
    const { spy } = renderAdd({
      lookup: () => {
        calls += 1;
        if (calls === 1) {
          // Capped outcome: retryable, so a same-term re-submit refetches.
          return {
            records: mockLookupCandidates,
            complete: false,
            truncated: true,
          };
        }
        throw cvUpstreamError();
      },
    });
    const user = await searchFor('saga');

    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    expect(screen.getByText(/Too many results/)).toBeInTheDocument();

    // Same term again: the capped envelope is not served from cache...
    await user.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() =>
      expect(
        screen.getByText('ComicVine lookup failed. Try again in a moment.'),
      ).toBeInTheDocument(),
    );
    const lookupCalls = spy.mock.calls.filter(
      ([path]) => path === '/api/v1/series/lookup?term=saga',
    );
    expect(lookupCalls).toHaveLength(2);
    // ...and the now-stale candidates must NOT render under the error.
    expect(screen.queryByTestId('candidate-40501234')).not.toBeInTheDocument();
    expect(screen.queryByText(/Too many results/)).not.toBeInTheDocument();
  });
});
