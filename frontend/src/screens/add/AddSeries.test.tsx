import { describe, it, expect, beforeEach } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route, useLocation, useNavigate } from 'react-router-dom';
import { renderWithProviders, type RouteEntry } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import {
  makeCommand,
  mockFormatProfiles,
  mockLookupCandidates,
  mockRootFolders,
  mockSeriesCreated,
  mockSuggestCandidates,
  pageOf,
} from '../../test/mockData';
import { useUiStore } from '../../store/uiStore';
import { ApiRequestError, isComicVineAuthError } from '../../api/fetcher';
import { SUGGEST_DEBOUNCE_MS } from '../../api/hooks';
import type {
  LookupCandidate,
  LookupResponse,
  RootFolderResource,
} from '../../api/types';
import { AddSeries, normalizeLookupTerm } from './AddSeries';
import { SeriesDetail } from '../series/SeriesDetail';

/**
 * Real-time wait past the autosuggest debounce interval (FRG-UI-005),
 * wrapped in `act` so the timer-driven state update it lets through is not
 * flagged as an out-of-band React update.
 */
function afterSuggestDebounce() {
  return act(() => new Promise((resolve) => setTimeout(resolve, SUGGEST_DEBOUNCE_MS + 100)));
}

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

/**
 * Default suggest resolver — a quiet no-op ({records: [], complete: true})
 * for any term, so the background autosuggest firing while these tests type
 * into the search input never surfaces an "unexpected request" against a
 * fetcher that doesn't expect it.
 */
function defaultSuggest(): unknown {
  return { records: [], complete: true };
}

function addFetcher({
  lookup = defaultLookup,
  suggest = defaultSuggest,
  rootFolders = () => mockRootFolders,
}: {
  lookup?: (path: string) => unknown;
  suggest?: (path: string) => unknown;
  rootFolders?: () => unknown;
} = {}) {
  return fakeFetcher((path, options) => {
    const method = options?.method ?? 'GET';
    if (method === 'GET' && path.startsWith('/api/v1/series/lookup/suggest?term=')) {
      return suggest(path);
    }
    if (method === 'GET' && path.startsWith('/api/v1/series/lookup?term=')) {
      return lookup(path);
    }
    if (method === 'GET' && path === '/api/v1/rootfolder') return rootFolders();
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

function renderAdd(
  overrides: {
    lookup?: (path: string) => unknown;
    suggest?: (path: string) => unknown;
    rootFolders?: () => unknown;
    route?: RouteEntry;
  } = {},
) {
  const { route, ...fetcherOverrides } = overrides;
  const { spy, fetcher } = addFetcher(fetcherOverrides);
  const utils = renderWithProviders(
    <Routes>
      <Route path="/add" element={<AddSeries />} />
      <Route path="/series/:id" element={<SeriesDetail />} />
    </Routes>,
    { fetcher, route: route ?? '/add' },
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
  it('FRG-UI-005 — search renders CV candidates as design-handoff result cards (cover, name, year, publisher, issue count, deck, In-library badge)', async () => {
    const { spy } = renderAdd();
    await searchFor('saga');

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series/lookup?term=saga'),
    );

    // Strong candidate: cover, name, year, publisher, issue count and a deck.
    const strong = screen.getByTestId('candidate-40501234');
    expect(
      within(strong).getByRole('img', { name: 'Saga cover' }),
    ).toBeInTheDocument();
    expect(within(strong).getByText('Saga')).toBeInTheDocument();
    expect(within(strong).getByText('(2012)')).toBeInTheDocument();
    expect(within(strong).getByText('Image')).toBeInTheDocument();
    expect(within(strong).getByText('63 issues')).toBeInTheDocument();
    // The deck renders with its residual CV markup stripped (no tags leak).
    expect(
      within(strong).getByText('Epic space opera about star-crossed lovers.'),
    ).toBeInTheDocument();
    expect(within(strong).queryByText(/</)).not.toBeInTheDocument();
    // The retired plausibility chips no longer render on the card face.
    expect(within(strong).queryByText(/Name match/)).not.toBeInTheDocument();
    expect(within(strong).queryByText(/Target issue/)).not.toBeInTheDocument();
    expect(within(strong).queryByText('In library')).not.toBeInTheDocument();

    // Weak candidate: already owned -> an "In library" badge shows; its
    // count_of_issues is null so the issue-count meta item is OMITTED.
    const weak = screen.getByTestId('candidate-40509999');
    expect(within(weak).getByText('In library')).toBeInTheDocument();
    expect(within(weak).queryByText(/\d+ issues?/)).not.toBeInTheDocument();
  });

  it('FRG-UI-005 / FRG-META-015 — candidates render in the API order, never client-reordered', async () => {
    // Feed candidates in a deliberate order (Saga first, Swamp Thing second);
    // the ranked API order is authoritative — the DOM must mirror it exactly.
    renderAdd();
    await searchFor('saga');

    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    const cards = screen.getAllByTestId(/^candidate-\d+$/);
    expect(cards.map((c) => c.getAttribute('data-testid'))).toEqual([
      'candidate-40501234',
      'candidate-40509999',
    ]);
  });

  it('FRG-UI-005 — selecting a candidate exposes root folder, format profile, monitor (segmented), collect-as (segmented) and search-on-add controls', async () => {
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

    // Monitor is now a segmented radiogroup exposing ALL six strategies, with
    // "All issues" selected by default (the pre-redesign default).
    const monitor = within(panel).getByRole('radiogroup', {
      name: 'Monitor strategy',
    });
    for (const label of [
      'All issues',
      'None',
      'Future issues',
      'Missing issues',
      'Existing issues',
      'First issue',
    ]) {
      expect(within(monitor).getByRole('radio', { name: label })).toBeInTheDocument();
    }
    expect(within(monitor).getByRole('radio', { name: 'All issues' })).toHaveAttribute(
      'aria-checked',
      'true',
    );

    // Collect-as is a segmented radiogroup with NO default selection (untouched
    // = derivation), so neither segment starts checked.
    const collect = within(panel).getByRole('radiogroup', { name: 'Collect as' });
    expect(
      within(collect).getByRole('radio', { name: 'Single Issues' }),
    ).toHaveAttribute('aria-checked', 'false');
    expect(
      within(collect).getByRole('radio', { name: 'Collected Editions' }),
    ).toHaveAttribute('aria-checked', 'false');

    expect(
      within(panel).getByRole('checkbox', { name: 'Start search for missing issues' }),
    ).toBeInTheDocument();
  });

  it('FRG-UI-012 / FRG-SER-008 — with no root folders registered the panel links to Media Management settings instead of a dead end', async () => {
    renderAdd({ rootFolders: () => [] });
    const user = await searchFor('saga');

    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Select Saga' }));

    const note = await screen.findByTestId('add-no-roots');
    expect(note).toHaveTextContent('No root folders are registered');
    expect(
      within(note).getByRole('link', { name: 'Media Management settings' }),
    ).toHaveAttribute('href', '/settings/media-management');
    // The dead-end select is gone and the add action stays disabled.
    expect(
      screen.queryByRole('combobox', { name: 'Root folder' }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId('ft-add-confirm')).toBeDisabled();
  });

  it('FRG-UI-034 — registering a root folder inline makes the dialog addable without losing the search results', async () => {
    // GET /api/v1/rootfolder starts empty, then returns the created folder once
    // the inline POST invalidates the list (mirroring the real refetch).
    let roots: RootFolderResource[] = [];
    const created: RootFolderResource = {
      id: 9,
      path: '/comics',
      free_space: null,
    };
    const { spy, fetcher } = fakeFetcher((path, options) => {
      const method = options?.method ?? 'GET';
      if (method === 'GET' && path.startsWith('/api/v1/series/lookup/suggest?term=')) {
        return { records: [], complete: true };
      }
      if (method === 'GET' && path.startsWith('/api/v1/series/lookup?term=')) {
        return defaultLookup(path);
      }
      if (method === 'GET' && path === '/api/v1/rootfolder') return roots;
      if (method === 'POST' && path === '/api/v1/rootfolder') {
        roots = [created];
        return created;
      }
      if (method === 'GET' && path === '/api/v1/formatprofile') return mockFormatProfiles;
      throw new Error(`unexpected request: ${method} ${path}`);
    });
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/add" element={<AddSeries />} />
      </Routes>,
      { fetcher, route: '/add' },
    );
    await user.type(screen.getByRole('searchbox', { name: 'Search ComicVine' }), 'saga');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Select Saga' }));

    // No roots yet: the inline registration form is offered (not a dead end).
    await screen.findByTestId('add-no-roots');
    await user.type(
      screen.getByRole('textbox', { name: 'New root folder path' }),
      '/comics',
    );
    await user.click(screen.getByTestId('add-register-root'));

    // The POST fired, the dialog now has the new root SELECTED, and it is addable.
    await waitFor(() =>
      expect(
        spy.mock.calls.some(
          ([p, o]) => p === '/api/v1/rootfolder' && o?.method === 'POST',
        ),
      ).toBe(true),
    );
    const rootFolder = await screen.findByRole('combobox', { name: 'Root folder' });
    await waitFor(() => expect(rootFolder).toHaveValue('9'));
    expect(screen.getByTestId('ft-add-confirm')).toBeEnabled();
    // The search results were never abandoned — the candidate is still present.
    expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument();
  });

  it('FRG-UI-034 — an inline registration refusal is shown verbatim and the operator can correct the path', async () => {
    const { fetcher } = fakeFetcher((path, options) => {
      const method = options?.method ?? 'GET';
      if (method === 'GET' && path.startsWith('/api/v1/series/lookup/suggest?term=')) {
        return { records: [], complete: true };
      }
      if (method === 'GET' && path.startsWith('/api/v1/series/lookup?term=')) {
        return defaultLookup(path);
      }
      if (method === 'GET' && path === '/api/v1/rootfolder') return [];
      if (method === 'POST' && path === '/api/v1/rootfolder') {
        throw new ApiRequestError(
          400,
          { message: "path '/humble' is not writable", errors: [] },
          '/api/v1/rootfolder',
        );
      }
      if (method === 'GET' && path === '/api/v1/formatprofile') return mockFormatProfiles;
      throw new Error(`unexpected request: ${method} ${path}`);
    });
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/add" element={<AddSeries />} />
      </Routes>,
      { fetcher, route: '/add' },
    );
    await user.type(screen.getByRole('searchbox', { name: 'Search ComicVine' }), 'saga');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Select Saga' }));

    await screen.findByTestId('add-no-roots');
    await user.type(
      screen.getByRole('textbox', { name: 'New root folder path' }),
      '/humble',
    );
    await user.click(screen.getByTestId('add-register-root'));

    // The backend's refusal is rendered verbatim; the input stays for a retry.
    const error = await screen.findByTestId('add-root-error');
    expect(error).toHaveTextContent("path '/humble' is not writable");
    expect(
      screen.getByRole('textbox', { name: 'New root folder path' }),
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
    // Monitor is segmented now: click the "Missing issues" segment, which maps
    // to the same monitor_strategy value the old <select> sent.
    await user.click(within(panel).getByRole('radio', { name: 'Missing issues' }));
    await user.click(
      within(panel).getByRole('checkbox', { name: 'Start search for missing issues' }),
    );
    await user.click(within(panel).getByRole('button', { name: 'Add Saga' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series', {
        method: 'POST',
        // Collect-as left untouched -> NO booktype key in the body (derivation).
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
 * FRG-UI-005 (m4-add-new) — the redesigned result card + inline panel: the
 * card expand/collapse behavior and the "Collect as" -> add-time booktype
 * mapping (untouched = no booktype key = derivation; Single Issues = "none";
 * Collected Editions = "tpb", FRG-SER-018). The full add machinery (ids/
 * navigate/refresh) is proven above; these pin the new controls.
 */
describe('FRG-UI-005: result card + collect-as (m4-add-new)', () => {
  it('FRG-UI-005 — a result card expands to the inline panel and collapses again', async () => {
    renderAdd();
    const user = await searchFor('saga');
    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    const toggle = screen.getByRole('button', { name: 'Select Saga' });

    // Collapsed initially.
    expect(screen.queryByTestId('add-options-panel')).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    // Click expands.
    await user.click(toggle);
    expect(screen.getByTestId('add-options-panel')).toBeInTheDocument();
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    // Clicking the card face again collapses.
    await user.click(toggle);
    expect(screen.queryByTestId('add-options-panel')).not.toBeInTheDocument();

    // Re-expand, then the panel's Cancel button collapses it too.
    await user.click(toggle);
    await user.click(
      within(screen.getByTestId('add-options-panel')).getByRole('button', {
        name: 'Cancel',
      }),
    );
    expect(screen.queryByTestId('add-options-panel')).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('FRG-UI-005 / FRG-SER-018 — "Single Issues" sends booktype "none"', async () => {
    const { spy } = renderAdd();
    const user = await searchFor('saga');
    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Select Saga' }));
    const panel = screen.getByTestId('add-options-panel');
    await waitFor(() =>
      expect(screen.getByTestId('ft-add-confirm')).not.toBeDisabled(),
    );

    await user.click(within(panel).getByRole('radio', { name: 'Single Issues' }));
    await user.click(within(panel).getByRole('button', { name: 'Add Saga' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series', {
        method: 'POST',
        body: {
          cv_volume_id: 40501234,
          root_folder_id: 1,
          format_profile_id: 1,
          monitor_strategy: 'all',
          monitor_new_items: 'all',
          search_on_add: false,
          booktype: 'none',
        },
      }),
    );
  });

  it('FRG-UI-005 / FRG-SER-018 — "Collected Editions" sends booktype "tpb"', async () => {
    const { spy } = renderAdd();
    const user = await searchFor('saga');
    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Select Saga' }));
    const panel = screen.getByTestId('add-options-panel');
    await waitFor(() =>
      expect(screen.getByTestId('ft-add-confirm')).not.toBeDisabled(),
    );

    await user.click(
      within(panel).getByRole('radio', { name: 'Collected Editions' }),
    );
    await user.click(within(panel).getByRole('button', { name: 'Add Saga' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series', {
        method: 'POST',
        body: {
          cv_volume_id: 40501234,
          root_folder_id: 1,
          format_profile_id: 1,
          monitor_strategy: 'all',
          monitor_new_items: 'all',
          search_on_add: false,
          booktype: 'tpb',
        },
      }),
    );
  });

  it('FRG-UI-005 / FRG-SER-018 — an untouched collect-as omits the booktype key entirely', async () => {
    const { spy } = renderAdd();
    const user = await searchFor('saga');
    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Select Saga' }));
    await waitFor(() =>
      expect(screen.getByTestId('ft-add-confirm')).not.toBeDisabled(),
    );
    // Add straight away without touching collect-as.
    await user.click(screen.getByRole('button', { name: 'Add Saga' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series', expect.anything()),
    );
    const seriesPost = spy.mock.calls.find(([path]) => path === '/api/v1/series');
    const postBody = seriesPost?.[1]?.body as Record<string, unknown> | undefined;
    expect(postBody).toBeDefined();
    expect(postBody).not.toHaveProperty('booktype');
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
      expect(screen.getByRole('alert')).toHaveTextContent(
        'ComicVine API key missing or invalid — check Settings.',
      ),
    );
    // The credential error must NOT be dressed up as "no results".
    expect(screen.queryByText(/No volumes found/)).not.toBeInTheDocument();
    // ...nor as the generic retry error.
    expect(screen.queryByText(/Try again in a moment/)).not.toBeInTheDocument();
  });

  it('FRG-UI-020 — the credential-error guidance links to Settings -> General', async () => {
    renderAdd({
      lookup: () => {
        throw cvAuthError();
      },
    });
    await searchFor('saga');

    const alert = await screen.findByRole('alert');
    expect(within(alert).getByRole('link', { name: 'check Settings' })).toHaveAttribute(
      'href',
      '/settings/general',
    );
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

/**
 * FRG-UI-005 (m2-search-autosuggest delta) — the debounced ComicVine
 * autosuggest riding FRG-API-017: threshold gating, debouncing, stale-term
 * discard, selection parity with a full-lookup candidate, the shared
 * credential-failure state, and the header quick-search prefill-on-mount
 * handoff. The full-lookup submit path (tested above) stays untouched.
 */
describe('FRG-UI-005: add series autosuggest (m2-search-autosuggest)', () => {
  it('FRG-UI-005 — no autosuggest request fires until the trimmed term is at least three characters', async () => {
    const { spy } = renderAdd();
    const user = userEvent.setup();
    await user.type(
      screen.getByRole('searchbox', { name: 'Search ComicVine' }),
      'sa',
    );
    await afterSuggestDebounce();

    expect(
      spy.mock.calls.some(([path]) =>
        String(path).startsWith('/api/v1/series/lookup/suggest?'),
      ),
    ).toBe(false);
    expect(screen.queryByTestId('suggest-dropdown')).not.toBeInTheDocument();
  });

  it('FRG-UI-005 — past the threshold, the suggest request is debounced and renders bounded ComicVine candidates', async () => {
    const { spy } = renderAdd({
      suggest: (path) =>
        path === '/api/v1/series/lookup/suggest?term=sag'
          ? { records: mockSuggestCandidates, complete: true }
          : { records: [], complete: true },
    });
    const user = userEvent.setup();
    await user.type(
      screen.getByRole('searchbox', { name: 'Search ComicVine' }),
      'sag',
    );

    await waitFor(() =>
      expect(screen.getByTestId('suggest-40501234')).toBeInTheDocument(),
    );
    const suggestCalls = spy.mock.calls.filter(([path]) =>
      String(path).startsWith('/api/v1/series/lookup/suggest?'),
    );
    // ONE request for the final settled term — not one per keystroke.
    expect(suggestCalls).toHaveLength(1);
    expect(suggestCalls[0][0]).toBe('/api/v1/series/lookup/suggest?term=sag');
  });

  it('FRG-UI-005 — a stale autosuggest response for a superseded term is discarded and never rendered', async () => {
    let resolveStale!: (value: unknown) => void;
    const staleResponse = new Promise((resolve) => {
      resolveStale = resolve;
    });
    renderAdd({
      suggest: (path) => {
        if (path === '/api/v1/series/lookup/suggest?term=sag') return staleResponse;
        if (path === '/api/v1/series/lookup/suggest?term=saga') {
          return { records: mockSuggestCandidates, complete: true };
        }
        return { records: [], complete: true };
      },
    });
    const user = userEvent.setup();
    const input = screen.getByRole('searchbox', { name: 'Search ComicVine' });

    await user.type(input, 'sag');
    await afterSuggestDebounce(); // 'sag' request now in flight, unresolved

    await user.type(input, 'a');
    await waitFor(() =>
      expect(screen.getByTestId('suggest-40501234')).toBeInTheDocument(),
    );

    // The stale 'sag' response finally arrives — it must not overwrite or
    // reintroduce anything under the current ('saga') dropdown.
    await act(async () => {
      resolveStale({
        records: [
          {
            cv_volume_id: 999,
            name: 'WRONG STALE RESULT',
            publisher: null,
            start_year: null,
            image_url: null,
            count_of_issues: null,
            have_it: false,
          },
        ],
        complete: true,
      });
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(screen.queryByTestId('suggest-999')).not.toBeInTheDocument();
    expect(screen.getByTestId('suggest-40501234')).toBeInTheDocument();
  });

  it('FRG-UI-005 — selecting a suggestion opens the same add panel as a full-lookup candidate, with no divergent add path', async () => {
    const { spy } = renderAdd({
      suggest: (path) =>
        path === '/api/v1/series/lookup/suggest?term=sag'
          ? { records: mockSuggestCandidates, complete: true }
          : { records: [], complete: true },
    });
    const user = userEvent.setup();
    await user.type(
      screen.getByRole('searchbox', { name: 'Search ComicVine' }),
      'sag',
    );

    await waitFor(() =>
      expect(screen.getByTestId('suggest-40501234')).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('button', { name: 'Select suggestion Saga' }));

    const panel = screen.getByTestId('add-options-panel');
    const rootFolder = within(panel).getByRole('combobox', { name: 'Root folder' });
    await waitFor(() =>
      expect(within(rootFolder).getAllByRole('option')).toHaveLength(2),
    );
    await user.click(within(panel).getByRole('button', { name: 'Add Saga' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/series', {
        method: 'POST',
        body: {
          cv_volume_id: 40501234,
          root_folder_id: 1,
          format_profile_id: 1,
          monitor_strategy: 'all',
          monitor_new_items: 'all',
          search_on_add: false,
        },
      }),
    );
    // Same navigate-to-detail-with-live-refresh outcome as the full-lookup path.
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Saga' })).toBeInTheDocument(),
    );
  });

  it('FRG-UI-005 — an autosuggest credential failure renders the same actionable Settings state as the full lookup', async () => {
    renderAdd({
      suggest: () => {
        throw cvAuthError();
      },
    });
    const user = userEvent.setup();
    await user.type(
      screen.getByRole('searchbox', { name: 'Search ComicVine' }),
      'sag',
    );

    await waitFor(() =>
      expect(
        within(screen.getByTestId('suggest-dropdown')).getByRole('alert'),
      ).toHaveTextContent('ComicVine API key missing or invalid — check Settings.'),
    );
    // Never dressed up as an empty dropdown.
    expect(screen.queryByTestId('suggest-40501234')).not.toBeInTheDocument();
  });

  it('FRG-UI-005 — a degraded (part-way-failed) autosuggest surfaces the failure note, not a silent empty dropdown', async () => {
    renderAdd({
      suggest: (path) =>
        path === '/api/v1/series/lookup/suggest?term=sag'
          ? { records: [], complete: false }
          : { records: [], complete: true },
    });
    const user = userEvent.setup();
    await user.type(
      screen.getByRole('searchbox', { name: 'Search ComicVine' }),
      'sag',
    );

    await waitFor(() =>
      expect(
        within(screen.getByTestId('suggest-dropdown')).getByRole('alert'),
      ).toHaveTextContent(/failed part-way/i),
    );
  });

  it('FRG-UI-005 — an incomplete autosuggest that still returned candidates renders them (accelerator does not nag)', async () => {
    renderAdd({
      suggest: (path) =>
        path === '/api/v1/series/lookup/suggest?term=sag'
          ? { records: mockSuggestCandidates, complete: false }
          : { records: [], complete: true },
    });
    const user = userEvent.setup();
    await user.type(
      screen.getByRole('searchbox', { name: 'Search ComicVine' }),
      'sag',
    );

    await waitFor(() =>
      expect(screen.getByTestId('suggest-40501234')).toBeInTheDocument(),
    );
    // no failure alert when candidates are present
    expect(
      within(screen.getByTestId('suggest-dropdown')).queryByRole('alert'),
    ).not.toBeInTheDocument();
  });

  it('FRG-UI-005 / FRG-UI-019 — a prefilled term (from the header quick-search fall-through) seeds the input and the autosuggest runs for it on mount', async () => {
    renderAdd({
      suggest: (path) =>
        path === '/api/v1/series/lookup/suggest?term=sag'
          ? { records: mockSuggestCandidates, complete: true }
          : { records: [], complete: true },
      route: { pathname: '/add', state: { prefillTerm: 'sag' } },
    });

    expect(screen.getByRole('searchbox', { name: 'Search ComicVine' })).toHaveValue(
      'sag',
    );
    await waitFor(() =>
      expect(screen.getByTestId('suggest-40501234')).toBeInTheDocument(),
    );
  });
});

/**
 * FRG-UI-005 / FRG-UI-019 — gate-review fixes for the autosuggest / header
 * quick-search seam: prefill is consumed via an effect (so a SECOND navigation
 * to an already-mounted Add Series re-seeds it) with the consumed state
 * stripped afterwards; and the debounced suggest surface never renders under a
 * newer input, nor alongside / duplicating a full-lookup submission for the
 * same term. The full-lookup outcome-state precedence (above) is untouched.
 */
function ReSeedButton({ term }: { term: string }) {
  const navigate = useNavigate();
  return (
    <button onClick={() => navigate('/add', { state: { prefillTerm: term } })}>
      reseed
    </button>
  );
}

function LocationStateProbe() {
  const location = useLocation();
  return <div data-testid="loc-state">{JSON.stringify(location.state)}</div>;
}

const BATMAN_SUGGEST = {
  records: [
    {
      cv_volume_id: 70701,
      name: 'Batman',
      publisher: 'DC Comics',
      start_year: 1940,
      image_url: null,
      count_of_issues: null,
      have_it: false,
    },
  ],
  complete: true,
};

describe('FRG-UI-005 / FRG-UI-019: autosuggest / quick-search seam (gate review)', () => {
  it('FRG-UI-019 — a second navigation to the already-mounted Add Series re-seeds the input and fires autosuggest for the new term', async () => {
    const { spy, fetcher } = addFetcher({
      suggest: (path) =>
        path === '/api/v1/series/lookup/suggest?term=batman'
          ? BATMAN_SUGGEST
          : { records: [], complete: true },
    });
    renderWithProviders(
      <>
        <ReSeedButton term="batman" />
        <Routes>
          <Route path="/add" element={<AddSeries />} />
          <Route path="/series/:id" element={<SeriesDetail />} />
        </Routes>
      </>,
      { fetcher, route: { pathname: '/add', state: { prefillTerm: 'saga' } } },
    );
    const user = userEvent.setup();

    // The first prefill seeds 'saga' on mount.
    expect(
      screen.getByRole('searchbox', { name: 'Search ComicVine' }),
    ).toHaveValue('saga');

    // A SECOND navigation to the same, still-mounted /add must re-seed the
    // input (same-route navigation does not remount) and drive the autosuggest
    // for the new term — a mount-time initializer would silently drop it.
    await user.click(screen.getByRole('button', { name: 'reseed' }));
    expect(
      screen.getByRole('searchbox', { name: 'Search ComicVine' }),
    ).toHaveValue('batman');
    await waitFor(() =>
      expect(screen.getByTestId('suggest-70701')).toBeInTheDocument(),
    );
    expect(
      spy.mock.calls.some(
        ([path]) => path === '/api/v1/series/lookup/suggest?term=batman',
      ),
    ).toBe(true);
  });

  it('FRG-UI-005 — a consumed prefill is stripped from navigation state so Back/refresh cannot re-seed a stale term', async () => {
    const { fetcher } = addFetcher();
    renderWithProviders(
      <Routes>
        <Route
          path="/add"
          element={
            <>
              <AddSeries />
              <LocationStateProbe />
            </>
          }
        />
      </Routes>,
      { fetcher, route: { pathname: '/add', state: { prefillTerm: 'saga' } } },
    );

    // The prefill still seeds the input on arrival...
    expect(
      screen.getByRole('searchbox', { name: 'Search ComicVine' }),
    ).toHaveValue('saga');
    // ...but the navigation state no longer carries it once consumed.
    await waitFor(() =>
      expect(screen.getByTestId('loc-state')).not.toHaveTextContent('saga'),
    );
  });

  it('FRG-UI-005 — typing past a settled suggestion immediately hides the stale candidates and its open add panel, before the debounce resolves the newer term', async () => {
    renderAdd({
      suggest: (path) =>
        path === '/api/v1/series/lookup/suggest?term=sag'
          ? { records: mockSuggestCandidates, complete: true }
          : // The newer term's request never resolves: this proves the old rows
            // are hidden by the input/settled-term mismatch, not by a new load.
            new Promise(() => {}),
    });
    const user = userEvent.setup();
    const input = screen.getByRole('searchbox', { name: 'Search ComicVine' });

    await user.type(input, 'sag');
    await waitFor(() =>
      expect(screen.getByTestId('suggest-40501234')).toBeInTheDocument(),
    );
    await user.click(
      screen.getByRole('button', { name: 'Select suggestion Saga' }),
    );
    expect(screen.getByTestId('add-options-panel')).toBeInTheDocument();

    // One more character supersedes the settled term; the stale candidate AND
    // its open panel must vanish at once, without waiting out the debounce.
    await user.type(input, 'a');
    expect(screen.queryByTestId('suggest-40501234')).not.toBeInTheDocument();
    expect(screen.queryByTestId('add-options-panel')).not.toBeInTheDocument();
  });

  it('FRG-UI-005 — a full-lookup submission suppresses the passive suggest surface for that term, which returns once the input diverges', async () => {
    renderAdd({
      suggest: () => ({ records: mockSuggestCandidates, complete: true }),
    });
    const user = await searchFor('saga');

    // The authoritative lookup results render for the submitted term...
    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    // ...and the passive suggest dropdown is suppressed — no duplicate list.
    expect(screen.queryByTestId('suggest-dropdown')).not.toBeInTheDocument();
    expect(screen.queryByTestId('suggest-40501234')).not.toBeInTheDocument();

    // Diverging the input from the submitted term brings the accelerator back.
    await user.type(
      screen.getByRole('searchbox', { name: 'Search ComicVine' }),
      'x',
    );
    await waitFor(() =>
      expect(screen.getByTestId('suggest-dropdown')).toBeInTheDocument(),
    );
  });

  it('FRG-UI-005 — a credential failure on both lookup and suggest for a submitted term renders exactly one alert', async () => {
    renderAdd({
      lookup: () => {
        throw cvAuthError();
      },
      suggest: () => {
        throw cvAuthError();
      },
    });
    await searchFor('saga');

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(
        'ComicVine API key missing or invalid — check Settings.',
      ),
    );
    // Suggest is suppressed post-submit, so the lookup's alert is not
    // duplicated by an identical suggest credential alert.
    expect(screen.getAllByRole('alert')).toHaveLength(1);
  });
});

/**
 * FRG-UI-032 — publisher-ignore-list results are recoverable in Add New: the
 * screen shows an explicit hidden count with a one-click reveal that refetches
 * with include-ignored and badges the flagged candidates, plus a path to edit
 * the list; nothing renders when the count is zero.
 */
describe('FRG-UI-032: hidden-by-ignore-list results are recoverable', () => {
  const IGNORED_CANDIDATE: LookupCandidate = {
    cv_volume_id: 40507777,
    name: 'Saga',
    publisher: 'Panini Verlag',
    start_year: 2015,
    image_url: null,
    count_of_issues: 10,
    description: null,
    name_similarity: 0.9,
    year_proximity: 3,
    target_issue_plausible: null,
    have_it: false,
    ignored: true,
  };

  /** Default search hides one volume; the include-ignored search reveals it flagged. */
  function ignoreLookup(path: string): LookupResponse {
    if (path === '/api/v1/series/lookup?term=saga&includeIgnored=true') {
      return {
        records: [...mockLookupCandidates, IGNORED_CANDIDATE],
        complete: true,
        truncated: false,
        hidden_by_ignore_list: 1,
      };
    }
    if (path === '/api/v1/series/lookup?term=saga') {
      return {
        records: mockLookupCandidates,
        complete: true,
        truncated: false,
        hidden_by_ignore_list: 1,
      };
    }
    return {
      records: [],
      complete: true,
      truncated: false,
      hidden_by_ignore_list: 0,
    };
  }

  it('FRG-UI-032 — a hidden-count line reveals flagged candidates on Show, with an Edit-list link to Settings', async () => {
    renderAdd({ lookup: ignoreLookup });
    const user = await searchFor('saga');

    const line = await screen.findByTestId('ignored-hidden-line');
    expect(line).toHaveTextContent(
      '1 result hidden by your publisher ignore list',
    );
    // The hidden candidate is not shown until the reveal is activated.
    expect(screen.queryByTestId('candidate-40507777')).not.toBeInTheDocument();

    await user.click(within(line).getByRole('button', { name: 'Show' }));

    // Revealed: the flagged candidate appears carrying its "Ignored" badge...
    const revealed = await screen.findByTestId('candidate-40507777');
    expect(
      within(revealed).getByTestId('candidate-40507777-ignored'),
    ).toHaveTextContent('Ignored');
    // ...the hidden-count line is replaced by an Edit-list pointer to Settings...
    expect(
      screen.queryByTestId('ignored-hidden-line'),
    ).not.toBeInTheDocument();
    const shown = screen.getByTestId('ignored-shown-line');
    expect(
      within(shown).getByRole('link', { name: 'Edit list' }),
    ).toHaveAttribute('href', '/settings/general');
    // ...and a non-ignored candidate carries no badge.
    expect(
      screen.queryByTestId('candidate-40501234-ignored'),
    ).not.toBeInTheDocument();
  });

  it('FRG-UI-032 — no hidden-results line renders when nothing was hidden', async () => {
    renderAdd(); // defaultLookup carries no hidden_by_ignore_list
    await searchFor('saga');

    await waitFor(() =>
      expect(screen.getByTestId('candidate-40501234')).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId('ignored-hidden-line'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('ignored-shown-line'),
    ).not.toBeInTheDocument();
  });
});
