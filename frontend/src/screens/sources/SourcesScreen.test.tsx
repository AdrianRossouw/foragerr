import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { createQueryClient } from '../../queryClient';
import { makeSeriesResource } from '../../test/mockData';
import { ApiRequestError, type Fetcher, type FetcherInit } from '../../api/fetcher';
import type {
  EntitlementResource,
  EntitlementDetailResource,
  StoreSourceResource,
} from '../../api/types';
import { SourcesScreen } from './SourcesScreen';

/*
 * FRG-UI-029 — the Sources screen: connect flow (masked input, live-validated
 * Connect, honest error), the manage view (count line, filter segments, review
 * actions incl. bulk + shift-range), and the reconcile chip edge rules.
 */

function makeSource(
  o: Partial<StoreSourceResource> & Pick<StoreSourceResource, 'id'>,
): StoreSourceResource {
  return {
    type: 'humble',
    name: 'Humble Bundle',
    connection_state: 'connected',
    auto_sync: false,
    last_sync_status: 'ok',
    settings: {},
    ...o,
  };
}

function ent(
  o: Partial<EntitlementResource> & Pick<EntitlementResource, 'id'>,
): EntitlementResource {
  return {
    source_id: 5,
    machine_name: `m-${o.id}`,
    human_name: `Item ${o.id}`,
    publisher: 'Image',
    classification: 'comic',
    review_status: 'new',
    download_state: null,
    download_error: null,
    preferred_format: 'CBZ',
    file_size: 1000,
    filename: `item-${o.id}.cbz`,
    proposed_series_id: null,
    matched_series_id: null,
    proposed_match: null,
    ...o,
  };
}

interface FetcherState {
  sources: StoreSourceResource[];
  entitlements: EntitlementResource[];
  details?: Record<number, EntitlementDetailResource>;
  calls: { path: string; init?: FetcherInit }[];
  /** Optional connect handler overriding the default success. */
  onConnect?: () => void;
  connectError?: ApiRequestError;
}

function makeFetcher(state: FetcherState): Fetcher {
  const resolve = async (path: string, init?: FetcherInit): Promise<unknown> => {
    const isWrite = !!init?.method && init.method !== 'GET';
    if (isWrite) state.calls.push({ path, init });

    // --- Writes (checked first so a POST to a read path is never shadowed) ---
    if (isWrite) {
      if (path === '/api/v1/sources') {
        if (state.connectError) throw state.connectError;
        state.onConnect?.();
        return {
          source: state.sources[0],
          order_count: 12,
          message: 'Connected — 12 order(s)',
        };
      }
      if (/\/api\/v1\/sources\/\d+\/sync$/.test(path)) {
        return { command_id: 1, status: 'queued' };
      }
      if (path === '/api/v1/sources/entitlements/bulk') {
        return { applied: 2, skipped: 0, errors: [] };
      }
      if (
        path.endsWith('/match') ||
        path.endsWith('/ignore') ||
        path.endsWith('/restore') ||
        path.endsWith('/add')
      ) {
        return ent({ id: 1 });
      }
      throw new Error(`unexpected write ${path}`);
    }

    // --- Reads ---
    if (path === '/api/v1/sources') return state.sources;
    if (path.startsWith('/api/v1/series?')) {
      return {
        page: 1,
        pageSize: 200,
        sortKey: 'sort_title',
        sortDirection: 'asc',
        totalRecords: 1,
        records: [makeSeriesResource({ id: 1, title: 'Descender' })],
      };
    }
    const detailMatch = path.match(/\/api\/v1\/sources\/entitlements\/(\d+)$/);
    if (detailMatch) {
      const id = Number(detailMatch[1]);
      return state.details?.[id] ?? { ...ent({ id }), fill_sets: [] };
    }
    if (/\/api\/v1\/sources\/\d+\/entitlements/.test(path)) {
      return state.entitlements;
    }
    throw new Error(`unexpected path ${path}`);
  };
  return resolve as unknown as Fetcher;
}

function renderScreen(state: FetcherState) {
  return renderWithProviders(<SourcesScreen />, {
    route: '/sources',
    client: createQueryClient(),
    fetcher: makeFetcher(state),
  });
}

describe('FRG-UI-029: connect flow', () => {
  it('FRG-UI-029 — the cookie field is masked and Connect is disabled until the paste threshold', async () => {
    const user = userEvent.setup();
    renderScreen({ sources: [], entitlements: [], calls: [] });

    const input = await screen.findByTestId('cookie-input');
    // Never echoed as plain text — the value is masked.
    expect(input).toHaveAttribute('type', 'password');

    const connect = screen.getByTestId('connect-button');
    expect(connect).toBeDisabled();

    await user.type(input, 'short');
    expect(connect).toBeDisabled();

    await user.clear(input);
    await user.type(input, '_simpleauth_sess=abcdefghijklmnop');
    expect(connect).toBeEnabled();
  });

  it('FRG-UI-029 — the helper reveals the extension "coming soon" chip and the DevTools cookie name', async () => {
    const user = userEvent.setup();
    renderScreen({ sources: [], entitlements: [], calls: [] });

    await user.click(await screen.findByTestId('helper-toggle'));
    const helper = screen.getByTestId('cookie-helper');
    expect(within(helper).getByText('Coming soon')).toBeInTheDocument();
    expect(within(helper).getByText('_simpleauth_sess')).toBeInTheDocument();
  });

  it('FRG-UI-029 — a successful Connect posts the cookie and lands on the manage view', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [],
      entitlements: [],
      calls: [],
      onConnect: () => {
        // The live validation passed — the source is now connected.
        state.sources = [makeSource({ id: 5, connection_state: 'connected' })];
      },
    };
    renderScreen(state);

    await user.type(await screen.findByTestId('cookie-input'), 'cookie-value-1234567890');
    await user.click(screen.getByTestId('connect-button'));

    // The manage view appears once the source flips to connected.
    await screen.findByTestId('store-manage');

    // The cookie rode in the request body under settings.session_cookie.
    const post = state.calls.find((c) => c.path === '/api/v1/sources');
    expect(post).toBeTruthy();
    const body = post!.init!.body as { settings: { session_cookie: string }; auto_sync: boolean };
    expect(body.settings.session_cookie).toBe('cookie-value-1234567890');
    expect(body.auto_sync).toBe(false);
  });

  it('FRG-UI-029 — a failed live validation surfaces the honest cause, nothing persisted', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [],
      entitlements: [],
      calls: [],
      connectError: new ApiRequestError(
        400,
        { message: 'Humble rejected the session cookie', errors: [] },
        '/api/v1/sources',
      ),
    };
    renderScreen(state);

    await user.type(await screen.findByTestId('cookie-input'), 'cookie-value-1234567890');
    await user.click(screen.getByTestId('connect-button'));

    const alert = await screen.findByTestId('connect-error');
    expect(alert).toHaveTextContent('Humble rejected the session cookie');
    // Still on the connect card — no manage view.
    expect(screen.queryByTestId('store-manage')).toBeNull();
  });
});

describe('FRG-UI-029: manage view review', () => {
  const source = makeSource({ id: 5, connection_state: 'connected' });
  const entitlements = [
    ent({
      id: 10,
      human_name: 'Descender, Vol. 1: Tin Stars',
      review_status: 'matched',
      matched_series_id: 1,
    }),
    ent({
      id: 11,
      human_name: 'Saga, Vol. 1',
      review_status: 'new',
      proposed_series_id: 1,
      proposed_match: {
        kind: 'library',
        series_id: 1,
        cv_volume_id: null,
        title: 'Saga',
        year: 2012,
        confidence: 0.93,
      },
    }),
    ent({ id: 12, human_name: 'Saga, Vol. 1 (Humble Choice copy)', review_status: 'ignored' }),
    ent({ id: 13, human_name: 'A Prose Novel', classification: 'other', review_status: 'new' }),
  ];

  it('FRG-UI-029 — the count line and status tags reflect the comic-scoped inventory', async () => {
    renderScreen({ sources: [source], entitlements, calls: [] });
    // Non-comic hidden by default → 3 comic items (1 matched, 1 new, 1 ignored).
    await waitFor(() =>
      expect(screen.getByTestId('count-line')).toHaveTextContent(
        '3 items · 1 matched · 1 new · 1 ignored',
      ),
    );
    // The ignored duplicate is dimmed with a Restore action.
    expect(screen.getByTestId('restore-12')).toBeInTheDocument();
    expect(screen.getByTestId('entitlement-row-12').className).toMatch(/rowIgnored/);
    // The new row offers Match-to-suggestion + Ignore.
    expect(screen.getByTestId('match-11')).toHaveTextContent('Match to Saga');
    expect(screen.getByTestId('ignore-11')).toBeInTheDocument();
  });

  it('FRG-UI-029 — filter segments narrow the list to a review status', async () => {
    const user = userEvent.setup();
    renderScreen({ sources: [source], entitlements, calls: [] });

    await user.click(await screen.findByTestId('filter-new'));
    expect(screen.getByTestId('entitlement-row-11')).toBeInTheDocument();
    expect(screen.queryByTestId('entitlement-row-10')).toBeNull();
    expect(screen.queryByTestId('entitlement-row-12')).toBeNull();
  });

  it('FRG-UI-029 — the non-comic toggle reveals "other" items on demand', async () => {
    const user = userEvent.setup();
    renderScreen({ sources: [source], entitlements, calls: [] });
    expect(screen.queryByTestId('entitlement-row-13')).toBeNull();
    await user.click(await screen.findByTestId('toggle-noncomic'));
    expect(screen.getByTestId('entitlement-row-13')).toBeInTheDocument();
  });

  it('FRG-UI-029 — matching a suggestion posts the proposed series id', async () => {
    const user = userEvent.setup();
    const state: FetcherState = { sources: [source], entitlements, calls: [] };
    renderScreen(state);
    await user.click(await screen.findByTestId('match-11'));
    await waitFor(() =>
      expect(
        state.calls.find((c) => c.path === '/api/v1/sources/entitlements/11/match'),
      ).toBeTruthy(),
    );
    const call = state.calls.find((c) => c.path.endsWith('/11/match'))!;
    expect((call.init!.body as { series_id: number }).series_id).toBe(1);
  });

  it('FRG-UI-029 — bulk select (with shift-range) applies one ignore action to the span', async () => {
    const user = userEvent.setup();
    const state: FetcherState = { sources: [source], entitlements, calls: [] };
    renderScreen(state);

    // Plain click the first row, shift-click the third → the visible span selects.
    await user.click(await screen.findByTestId('select-10'));
    await user.keyboard('{Shift>}');
    await user.click(screen.getByTestId('select-12'));
    await user.keyboard('{/Shift}');

    const bar = await screen.findByTestId('bulk-bar');
    expect(bar).toHaveTextContent('3 selected');

    await user.click(screen.getByTestId('bulk-ignore'));
    await waitFor(() =>
      expect(
        state.calls.find((c) => c.path === '/api/v1/sources/entitlements/bulk'),
      ).toBeTruthy(),
    );
    const bulk = state.calls.find((c) => c.path.endsWith('/bulk'))!;
    const body = bulk.init!.body as { action: string; entitlement_ids: number[] };
    expect(body.action).toBe('ignore');
    expect(body.entitlement_ids.sort()).toEqual([10, 11, 12]);
  });
});

describe('FRG-UI-029: reconcile chip edge rules', () => {
  const source = makeSource({ id: 5, connection_state: 'connected' });

  function detail(id: number, fill_sets: EntitlementDetailResource['fill_sets']): EntitlementDetailResource {
    return { ...ent({ id, review_status: 'matched', matched_series_id: 1 }), fill_sets };
  }

  it('FRG-UI-029 — an owned single is chipped amber and kept; fillable issues are green', async () => {
    const user = userEvent.setup();
    const entitlements = [
      ent({ id: 20, human_name: 'Descender, Vol. 1', review_status: 'matched', matched_series_id: 1 }),
    ];
    const details = {
      20: detail(20, [
        {
          trade_issue_id: 900,
          standalone: false,
          ranges: [
            {
              target_series_id: 1,
              range_label: '1-6',
              issues: [
                { issue_id: 1, issue_number: '1', ownership: 'fillable' },
                { issue_id: 3, issue_number: '3', ownership: 'single' },
              ],
            },
          ],
        },
      ]),
    };
    renderScreen({ sources: [source], entitlements, details, calls: [] });

    await user.click(await screen.findByTestId('expand-20'));
    const panel = await screen.findByTestId('detail-20');
    // The owned single (#3) is chipped amber (kept, never replaced).
    const owned = within(panel).getByText('#3');
    expect(owned).toHaveAttribute('data-owned', 'true');
    // The fillable single (#1) is chipped green.
    expect(within(panel).getByText('#1')).toHaveAttribute('data-owned', 'false');
    // …and the no-double-counting reconcile note is present.
    expect(panel).toHaveTextContent(/keeps the single and fills only the remaining/);
  });

  it('FRG-UI-029 — a range above 12 issues renders text-only (chips suppressed)', async () => {
    const user = userEvent.setup();
    const issues = Array.from({ length: 13 }, (_, i) => ({
      issue_id: i + 1,
      issue_number: String(i + 1),
      ownership: 'fillable' as const,
    }));
    const entitlements = [ent({ id: 21, human_name: 'Compendium One', review_status: 'matched', matched_series_id: 1 })];
    const details = {
      21: detail(21, [{ trade_issue_id: 901, standalone: false, ranges: [{ target_series_id: 1, range_label: '1-13', issues }] }]),
    };
    renderScreen({ sources: [source], entitlements, details, calls: [] });

    await user.click(await screen.findByTestId('expand-21'));
    const panel = await screen.findByTestId('detail-21');
    expect(panel).toHaveTextContent('Marks 13 issues (#1-13) as owned.');
    // No individual chips were rendered for the suppressed range.
    expect(within(panel).queryByText('#1')).toBeNull();
  });

  it('FRG-UI-029 — a standalone OGN/artbook fabricates no singles', async () => {
    const user = userEvent.setup();
    const entitlements = [ent({ id: 22, human_name: 'The Art of Saga', review_status: 'matched', matched_series_id: 1 })];
    const details = {
      22: detail(22, [{ trade_issue_id: 902, standalone: true, ranges: [] }]),
    };
    renderScreen({ sources: [source], entitlements, details, calls: [] });

    await user.click(await screen.findByTestId('expand-22'));
    const panel = await screen.findByTestId('detail-22');
    expect(panel).toHaveTextContent(/No single issues to fill/);
  });
});
