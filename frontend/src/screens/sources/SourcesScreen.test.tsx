import { describe, it, expect } from 'vitest';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { createQueryClient } from '../../queryClient';
import { makeCommand, makeSeriesResource } from '../../test/mockData';
import { SUGGEST_DEBOUNCE_MS } from '../../api/hooks';
import { ApiRequestError, type Fetcher, type FetcherInit } from '../../api/fetcher';
import type {
  EntitlementResource,
  EntitlementDetailResource,
  SeriesResource,
  StoreSourceResource,
} from '../../api/types';
import { SourcesScreen } from './SourcesScreen';

/*
 * FRG-UI-029 — the Sources screen: connect flow (masked input, live-validated
 * Connect, honest error), the manage view (count line, filter segments, review
 * actions incl. bulk + shift-range, virtualized at corpus scale), the per-row
 * ComicVine search picker (FRG-UI-039), and the reconcile chip edge rules.
 */

/** Real-time wait past the row search's autosuggest debounce (FRG-UI-039). */
function afterSuggestDebounce() {
  return act(
    () => new Promise((resolve) => setTimeout(resolve, SUGGEST_DEBOUNCE_MS + 100)),
  );
}

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
    bundle_human_name: null,
    // The SERVER computes group_key (matching_key(query_term(human_name))) —
    // the fixture states it as a LITERAL per row rather than re-implementing
    // the fold, which is the whole point of it being server-side. The default
    // is unique per row, so a fixture only groups when it says so.
    group_key: `item-${o.id}`,
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
  /** Optional reconnect handler overriding the default success. */
  onReconnect?: () => void;
  reconnectError?: ApiRequestError;
  /** Error the retry-download endpoint rejects with (e.g. a 409 conflict). */
  retryError?: ApiRequestError;
  /** Error the bulk recompute rejects with (e.g. the 409 no-ComicVine-key). */
  recomputeError?: ApiRequestError;
  /**
   * Gate on the recompute's 202 (FRG-SRC-013): an unresolved promise here keeps
   * the mutation in flight, so a test can observe the pending/disabled state.
   */
  recomputeGate?: Promise<void>;
  /**
   * Bulk-endpoint result (FRG-SRC-011). Receives the request body so a test can
   * assert on it and mutate `state.entitlements` to model the rows the server
   * actually applied; defaults to "everything applied, no per-row errors".
   */
  bulkResult?: (body: { action: string; entitlement_ids: number[] }) => unknown;
  /** Library series the match-picker / booktype lookups resolve against;
   * defaults to a single "Driftwood" series (booktype null) when omitted. */
  librarySeries?: SeriesResource[];
  /** The command GET /api/v1/command/{id} resolves to for the sync watcher;
   * defaults to a `started` (still-running) command. */
  commandStatus?: ReturnType<typeof makeCommand>;
  /** Row-search full-lookup resolver (FRG-UI-039); may throw an
   * `ApiRequestError` to exercise the credential/upstream outcome notes.
   * Defaults to a clean-empty envelope. */
  lookup?: (path: string) => unknown;
  /** Row-search autosuggest resolver; defaults to a quiet empty dropdown so
   * the debounced accelerator never surfaces an unexpected-path throw. */
  suggest?: (path: string) => unknown;
  /** When present, every READ path is recorded here (writes go to `calls`). */
  reads?: string[];
}

/** A ComicVine candidate as the lookup/suggest endpoints shape it. */
function candidate(
  o: Partial<{
    cv_volume_id: number;
    name: string;
    publisher: string | null;
    start_year: number | null;
    count_of_issues: number | null;
    have_it: boolean;
  }> & { cv_volume_id: number },
) {
  return {
    name: `Volume ${o.cv_volume_id}`,
    publisher: 'Image',
    start_year: 2012,
    image_url: null,
    count_of_issues: 54,
    description: null,
    name_similarity: 0.9,
    year_proximity: null,
    target_issue_plausible: null,
    have_it: false,
    ...o,
  };
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
      const reconnectMatch = path.match(/^\/api\/v1\/sources\/(\d+)\/reconnect$/);
      if (reconnectMatch) {
        if (state.reconnectError) throw state.reconnectError;
        state.onReconnect?.();
        const id = Number(reconnectMatch[1]);
        return {
          source: state.sources.find((s) => s.id === id) ?? state.sources[0],
          order_count: 12,
          message: 'Reconnected — 12 order(s)',
        };
      }
      const disconnectMatch = path.match(/^\/api\/v1\/sources\/(\d+)\/disconnect$/);
      if (disconnectMatch) {
        const id = Number(disconnectMatch[1]);
        // Disconnect drops the credential but keeps the row (and its synced
        // data) around in a `disconnected` state — mirrors the backend.
        state.sources = state.sources.map((s) =>
          s.id === id ? { ...s, connection_state: 'disconnected' as const } : s,
        );
        return state.sources.find((s) => s.id === id);
      }
      if (/\/api\/v1\/sources\/\d+\/sync$/.test(path)) {
        return { command_id: 1, status: 'queued' };
      }
      // Bulk proposal recompute (FRG-SRC-013): 202 with the queued command, or
      // the backend's 409 when no ComicVine key is configured.
      if (/^\/api\/v1\/sources\/\d+\/recompute-proposals$/.test(path)) {
        if (state.recomputeError) throw state.recomputeError;
        if (state.recomputeGate) await state.recomputeGate;
        return { command_id: 7, status: 'queued' };
      }
      // PATCH /sources/{id} — flip a mutable control (auto_sync). Mutate the
      // in-memory source so the invalidation-driven refetch reflects it.
      const patchMatch = path.match(/^\/api\/v1\/sources\/(\d+)$/);
      if (patchMatch && init?.method === 'PATCH') {
        const id = Number(patchMatch[1]);
        const body = init.body as { auto_sync?: boolean };
        state.sources = state.sources.map((s) =>
          s.id === id
            ? {
                ...s,
                ...(body.auto_sync !== undefined
                  ? { auto_sync: body.auto_sync }
                  : {}),
              }
            : s,
        );
        return state.sources.find((s) => s.id === id);
      }
      if (path === '/api/v1/sources/entitlements/bulk') {
        const body = init!.body as {
          action: string;
          entitlement_ids: number[];
        };
        return (
          state.bulkResult?.(body) ?? {
            applied: body.entitlement_ids.length,
            skipped: 0,
            errors: {},
          }
        );
      }
      // Retry re-queues a failed download: the backend clears the failure, so
      // the in-memory row flips out of `failed` for the refetch that follows.
      const retryMatch = path.match(
        /^\/api\/v1\/sources\/entitlements\/(\d+)\/retry-download$/,
      );
      if (retryMatch) {
        if (state.retryError) throw state.retryError;
        const id = Number(retryMatch[1]);
        state.entitlements = state.entitlements.map((e) =>
          e.id === id
            ? { ...e, download_state: 'queued', download_error: null }
            : e,
        );
        return state.entitlements.find((e) => e.id === id);
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
    state.reads?.push(path);
    if (path.startsWith('/api/v1/series/lookup/suggest?term=')) {
      return state.suggest?.(path) ?? { records: [], complete: true };
    }
    if (path.startsWith('/api/v1/series/lookup?term=')) {
      return (
        state.lookup?.(path) ?? { records: [], complete: true, truncated: false }
      );
    }
    if (path === '/api/v1/sources') return state.sources;
    if (path.startsWith('/api/v1/series?')) {
      const records = state.librarySeries ?? [
        makeSeriesResource({ id: 1, title: 'Driftwood' }),
      ];
      return {
        page: 1,
        pageSize: 200,
        sortKey: 'sort_title',
        sortDirection: 'asc',
        totalRecords: records.length,
        records,
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
    if (/^\/api\/v1\/command\/\d+$/.test(path)) {
      // The "Sync now" watcher: defaults to a still-running command so a
      // sync-in-progress test can observe the spinner state deterministically.
      return state.commandStatus ?? makeCommand({ id: 1, name: 'humble-sync', status: 'started' });
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

  it('FRG-UI-029 — the helper points to the browser extension and names the DevTools cookie', async () => {
    const user = userEvent.setup();
    renderScreen({ sources: [], entitlements: [], calls: [] });

    await user.click(await screen.findByTestId('helper-toggle'));
    const helper = screen.getByTestId('cookie-helper');
    expect(within(helper).getByText(/browser extension/)).toBeInTheDocument();
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
      human_name: 'Driftwood, Vol. 1: Ash Stars',
      review_status: 'matched',
      matched_series_id: 1,
    }),
    ent({
      id: 11,
      human_name: 'Vane, Vol. 1',
      review_status: 'new',
      proposed_series_id: 1,
      proposed_match: {
        kind: 'library',
        series_id: 1,
        cv_volume_id: null,
        title: 'Vane',
        year: 2012,
        confidence: 0.93,
      },
    }),
    ent({ id: 12, human_name: 'Vane, Vol. 1 (Humble Choice copy)', review_status: 'ignored' }),
    ent({ id: 13, human_name: 'A Prose Novel', classification: 'other', review_status: 'new' }),
  ];

  it('FRG-UI-029 — the auto-sync toggle is operable and PATCHes the source', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [makeSource({ id: 5, auto_sync: false })],
      entitlements,
      calls: [],
    };
    renderScreen(state);

    const toggle = await screen.findByTestId('auto-sync-manage');
    // Ships OFF and is NOT disabled (it is wired to the PATCH endpoint).
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    expect(toggle).not.toBeDisabled();

    await user.click(toggle);
    await waitFor(() =>
      expect(
        state.calls.find(
          (c) => c.path === '/api/v1/sources/5' && c.init?.method === 'PATCH',
        ),
      ).toBeTruthy(),
    );
    const patch = state.calls.find((c) => c.path === '/api/v1/sources/5')!;
    expect((patch.init!.body as { auto_sync: boolean }).auto_sync).toBe(true);
    // After the invalidation-driven refetch the switch reflects ON.
    await waitFor(() =>
      expect(screen.getByTestId('auto-sync-manage')).toHaveAttribute(
        'aria-checked',
        'true',
      ),
    );
  });

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
    expect(screen.getByTestId('match-11')).toHaveTextContent('Match to Vane');
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
      ent({ id: 20, human_name: 'Driftwood, Vol. 1', review_status: 'matched', matched_series_id: 1 }),
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
    const entitlements = [ent({ id: 22, human_name: 'The Art of Vane', review_status: 'matched', matched_series_id: 1 })];
    const details = {
      22: detail(22, [{ trade_issue_id: 902, standalone: true, ranges: [] }]),
    };
    renderScreen({ sources: [source], entitlements, details, calls: [] });

    await user.click(await screen.findByTestId('expand-22'));
    const panel = await screen.findByTestId('detail-22');
    expect(panel).toHaveTextContent(/No single issues to fill/);
  });
});

describe('FRG-UI-029: reconnect, disconnect, connected-empty, and sync-in-progress', () => {
  it('FRG-UI-029 — reconnecting from the expired state clears the amber reconnect UI and lands on the manage view', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [makeSource({ id: 5, connection_state: 'expired' })],
      entitlements: [],
      calls: [],
      onReconnect: () => {
        // The live validation passed — the session is fresh again.
        state.sources = [makeSource({ id: 5, connection_state: 'connected' })];
      },
    };
    renderScreen(state);

    // The ConnectCard's `reconnecting` branch: reconnect title + the amber
    // "session kept" note.
    expect(
      await screen.findByText('Reconnect your Humble Bundle account'),
    ).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent(/previous session expired/);

    await user.type(screen.getByTestId('cookie-input'), 'fresh-cookie-1234567890');
    await user.click(screen.getByTestId('connect-button'));

    // The manage view appears once the source flips back to connected — the
    // amber reconnect card and its note are both gone (all cleared).
    await screen.findByTestId('store-manage');
    expect(screen.queryByTestId('connect-card')).toBeNull();
    expect(screen.queryByRole('note')).toBeNull();

    const post = state.calls.find((c) => c.path === '/api/v1/sources/5/reconnect');
    expect(post).toBeTruthy();
    const body = post!.init!.body as { settings: { session_cookie: string } };
    expect(body.settings.session_cookie).toBe('fresh-cookie-1234567890');
  });

  it('FRG-UI-029 — a connected store with no entitlements yet renders the empty-list message', async () => {
    const source = makeSource({ id: 5, connection_state: 'connected' });
    renderScreen({ sources: [source], entitlements: [], calls: [] });

    const empty = await screen.findByTestId('empty-list');
    expect(empty).toHaveTextContent(
      'Nothing to review here yet — Humble purchases appear after a sync.',
    );
  });

  it('FRG-UI-029 — Disconnect calls the endpoint and returns to the unconfigured connect state', async () => {
    const user = userEvent.setup();
    const source = makeSource({ id: 5, connection_state: 'connected' });
    const state: FetcherState = { sources: [source], entitlements: [], calls: [] };
    renderScreen(state);

    await user.click(await screen.findByTestId('disconnect'));
    await waitFor(() =>
      expect(
        state.calls.find((c) => c.path === '/api/v1/sources/5/disconnect'),
      ).toBeTruthy(),
    );

    // Back on the connect card in its plain (non-reconnecting) state.
    await screen.findByTestId('connect-card');
    expect(screen.getByText('Connect your Humble Bundle account')).toBeInTheDocument();
    expect(screen.queryByTestId('store-manage')).toBeNull();
  });

  it('FRG-UI-029 — Sync now shows the spinner/pending state while a sync is running', async () => {
    const user = userEvent.setup();
    const source = makeSource({ id: 5, connection_state: 'connected' });
    renderScreen({ sources: [source], entitlements: [], calls: [] });

    const syncBtn = await screen.findByTestId('sync-now');
    expect(syncBtn).toHaveTextContent('Sync now');

    await user.click(syncBtn);

    // The command watcher's default `started` status keeps `syncing` true.
    await waitFor(() => expect(syncBtn).toHaveTextContent('Syncing…'));
    expect(syncBtn.querySelector('i')!.className).toMatch(/spin/);
    expect(syncBtn).toBeDisabled();
  });
});

describe('FRG-UI-029: a matched row prefers the linked series booktype over the file format', () => {
  const source = makeSource({ id: 5, connection_state: 'connected' });

  it('FRG-UI-029 — a matched row whose library series carries a booktype shows the booktype chip, not the file format', async () => {
    const entitlements = [
      ent({
        id: 30,
        human_name: 'Driftwood, Vol. 1: Ash Stars',
        review_status: 'matched',
        matched_series_id: 1,
        preferred_format: 'CBZ',
      }),
    ];
    renderScreen({
      sources: [source],
      entitlements,
      calls: [],
      librarySeries: [makeSeriesResource({ id: 1, title: 'Driftwood', booktype: 'tpb' })],
    });

    const row = await screen.findByTestId('entitlement-row-30');
    const badge = within(row).getByTestId('booktype-badge');
    expect(badge).toHaveTextContent('TPB');
    // The decorative aria-hidden spine still shows the raw format — only the
    // visible title-row chip swaps to the booktype badge.
    expect(
      within(row).queryByText('CBZ', { selector: '[class*="chip"]' }),
    ).toBeNull();
  });

  it('FRG-UI-029 — a new row (no linked series yet) still shows the file-format chip', async () => {
    const entitlements = [
      ent({
        id: 31,
        human_name: 'Vane, Vol. 1',
        review_status: 'new',
        preferred_format: 'CBZ',
      }),
    ];
    renderScreen({
      sources: [source],
      entitlements,
      calls: [],
      librarySeries: [makeSeriesResource({ id: 1, title: 'Driftwood', booktype: 'tpb' })],
    });

    const row = await screen.findByTestId('entitlement-row-31');
    expect(
      within(row).getByText('CBZ', { selector: '[class*="chip"]' }),
    ).toBeInTheDocument();
    expect(within(row).queryByTestId('booktype-badge')).toBeNull();
  });

  it('FRG-UI-029 — a matched row whose library series has no booktype falls back to the file-format chip', async () => {
    const entitlements = [
      ent({
        id: 32,
        human_name: 'Some Ongoing, Vol. 1',
        review_status: 'matched',
        matched_series_id: 1,
        preferred_format: 'PDF',
      }),
    ];
    renderScreen({
      sources: [source],
      entitlements,
      calls: [],
      librarySeries: [makeSeriesResource({ id: 1, title: 'Driftwood', booktype: null })],
    });

    const row = await screen.findByTestId('entitlement-row-32');
    expect(
      within(row).getByText('PDF', { selector: '[class*="chip"]' }),
    ).toBeInTheDocument();
    expect(within(row).queryByTestId('booktype-badge')).toBeNull();
  });
});

/*
 * FRG-SRC-009 — a failed source download is not a dead end: the row carries the
 * failure reason AND an explicit Retry that re-queues the grab.
 */
describe('FRG-SRC-009: failed-download retry affordance', () => {
  const source = makeSource({ id: 5, connection_state: 'connected' });

  const failed = ent({
    id: 40,
    human_name: 'Synthetic Hero #1',
    review_status: 'matched',
    matched_series_id: 1,
    download_state: 'failed',
    download_error: 'md5 mismatch on the downloaded file',
  });

  it('FRG-SRC-009 — a failed row shows the reason and a Retry that posts retry-download', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: [failed],
      calls: [],
    };
    renderScreen(state);

    const row = await screen.findByTestId('entitlement-row-40');
    // The honest reason is still shown alongside the new affordance.
    expect(row).toHaveTextContent('md5 mismatch on the downloaded file');

    await user.click(within(row).getByTestId('retry-40'));
    await waitFor(() =>
      expect(
        state.calls.find(
          (c) =>
            c.path === '/api/v1/sources/entitlements/40/retry-download' &&
            c.init?.method === 'POST',
        ),
      ).toBeTruthy(),
    );
    // The re-queued row is no longer failed, so the affordance retires with it.
    await waitFor(() =>
      expect(screen.queryByTestId('retry-40')).toBeNull(),
    );
  });

  it('FRG-SRC-009 — a rejected retry (409 on a no-longer-failed row) leaves the row intact', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: [failed],
      calls: [],
      retryError: new ApiRequestError(
        409,
        { message: 'entitlement 40 is queued, not failed', errors: [] },
        '/api/v1/sources/entitlements/40/retry-download',
      ),
    };
    renderScreen(state);

    const row = await screen.findByTestId('entitlement-row-40');
    await user.click(within(row).getByTestId('retry-40'));
    await waitFor(() =>
      expect(
        state.calls.find((c) => c.path.endsWith('/40/retry-download')),
      ).toBeTruthy(),
    );
    // Nothing is lost on a stale click: the reason and the affordance remain.
    expect(await screen.findByTestId('retry-40')).toBeEnabled();
    expect(screen.getByTestId('entitlement-row-40')).toHaveTextContent(
      'md5 mismatch on the downloaded file',
    );
  });

  it('FRG-SRC-009 — rows that have not failed carry no Retry', async () => {
    renderScreen({
      sources: [source],
      entitlements: [
        ent({ id: 41, review_status: 'matched', download_state: 'imported' }),
        ent({ id: 42, review_status: 'new', download_state: null }),
      ],
      calls: [],
    });

    await screen.findByTestId('entitlement-row-41');
    expect(screen.queryByTestId('retry-41')).toBeNull();
    expect(screen.queryByTestId('retry-42')).toBeNull();
  });
});

/*
 * FRG-UI-039 — the per-row ComicVine search picker: the add-screen lookup
 * surface (debounced suggest, full search, in-library marking, outcome notes)
 * mounted on EVERY reviewable row, so "no plausible automatic match" is a
 * verdict beside a live search rather than a dead end. Picking an in-library
 * volume matches; picking one that is not adds and matches in one action.
 */
describe('FRG-UI-039: search seed precedence', () => {
  it('FRG-UI-039 — seeds from the server group_key, falling back to the trimmed title', async () => {
    const { searchSeedTerm } = await import('./EntitlementSearch');
    expect(searchSeedTerm('TITLE Vol. 243 #3', 'title')).toBe('title');
    expect(searchSeedTerm('Plain Title #12', '')).toBe('Plain Title');
    expect(searchSeedTerm('Plain Title #12', null)).toBe('Plain Title');
  });
});

describe('FRG-UI-039: per-row ComicVine search', () => {
  const source = makeSource({ id: 5, connection_state: 'connected' });
  /**
   * A row the proposal pass RAN on and could not place — the dead-end case.
   * The backend stores that as a verdict MARKER (not a null), so the UI can
   * tell "we looked and nothing fit" apart from "not computed yet".
   */
  const orphan = ent({
    id: 50,
    human_name: 'Nobody is Guarding the Lighthouse Vol. 8 #3',
    group_key: 'nobody is guarding lighthouse',
    review_status: 'new',
    proposed_match: {
      verdict: 'no-plausible-match',
      universe: 'comicvine',
      candidates: [],
      auto: false,
    },
    proposed_series_id: null,
  });
  const library = [
    makeSeriesResource({ id: 1, title: 'Driftwood' }), // cv_volume_id 40500001
  ];

  it('FRG-UI-039 — a row with no plausible match still offers a search, and typing fires the debounced suggest', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: [orphan],
      calls: [],
      reads: [],
      librarySeries: library,
      suggest: () => ({
        records: [candidate({ cv_volume_id: 4050_1234, name: 'WDTG' })],
        complete: true,
      }),
    };
    renderScreen(state);

    // The automatic verdict is informational — and sits beside the search.
    expect(await screen.findByTestId('no-match-50')).toHaveTextContent(
      'No plausible match',
    );
    await user.click(screen.getByTestId('search-50'));

    const panel = await screen.findByTestId('row-search-50');
    expect(within(panel).getByTestId('row-search-note-50')).toHaveTextContent(
      'No plausible automatic match',
    );
    // The seed is the SERVER's stripped series-shaped fold (group_key), so
    // edition boilerplate never empties the suggest (live-rig finding).
    const input = within(panel).getByTestId('row-search-input-50');
    expect(input).toHaveValue('nobody is guarding lighthouse');

    await user.clear(input);
    await user.type(input, 'guarding lighthouse');
    await afterSuggestDebounce();

    await waitFor(() =>
      expect(
        state.reads!.some((p) =>
          p.startsWith('/api/v1/series/lookup/suggest?term=guarding%20lighthouse'),
        ),
      ).toBe(true),
    );
    // …and the accelerator's candidates are pickable straight from the dropdown.
    expect(await screen.findByTestId('cand-50-40501234')).toBeInTheDocument();
  });

  it('FRG-UI-039 — an in-library result is marked and picking it matches the row, creating nothing', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: [orphan],
      calls: [],
      librarySeries: library,
      lookup: () => ({
        records: [
          candidate({
            cv_volume_id: 4050_0001,
            name: 'Driftwood',
            have_it: true,
          }),
          candidate({ cv_volume_id: 4050_9999, name: 'Some Other Volume' }),
        ],
        complete: true,
        truncated: false,
      }),
    };
    renderScreen(state);

    await user.click(await screen.findByTestId('search-50'));
    await user.click(within(screen.getByTestId('row-search-50')).getByRole('button', { name: 'Search' }));

    const owned = await screen.findByTestId('cand-50-40500001');
    // Visibly marked as already in the library.
    expect(within(owned).getByTestId('cand-50-40500001-have')).toHaveTextContent(
      'In library',
    );

    await user.click(owned);
    await waitFor(() =>
      expect(
        state.calls.find((c) => c.path === '/api/v1/sources/entitlements/50/match'),
      ).toBeTruthy(),
    );
    const call = state.calls.find((c) => c.path.endsWith('/50/match'))!;
    // Linked to the LOCAL series id the owned CV volume maps to — no add.
    expect((call.init!.body as { series_id: number }).series_id).toBe(1);
    expect(state.calls.find((c) => c.path.endsWith('/50/add'))).toBeUndefined();
  });

  it('FRG-UI-039 — picking a result that is not in the library adds and matches it with the explicit cv_volume_id', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: [orphan],
      calls: [],
      librarySeries: library,
      lookup: () => ({
        records: [candidate({ cv_volume_id: 4050_7777, name: 'WDTG' })],
        complete: true,
        truncated: false,
      }),
    };
    renderScreen(state);

    await user.click(await screen.findByTestId('search-50'));
    await user.click(within(screen.getByTestId('row-search-50')).getByRole('button', { name: 'Search' }));
    await user.click(await screen.findByTestId('cand-50-40507777'));

    await waitFor(() =>
      expect(
        state.calls.find((c) => c.path === '/api/v1/sources/entitlements/50/add'),
      ).toBeTruthy(),
    );
    const call = state.calls.find((c) => c.path.endsWith('/50/add'))!;
    expect((call.init!.body as { cv_volume_id: number }).cv_volume_id).toBe(
      4050_7777,
    );
  });

  it('FRG-UI-039 — a matched row can Change its match through the same search surface', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: [
        ent({
          id: 51,
          human_name: 'Driftwood, Vol. 1',
          review_status: 'matched',
          matched_series_id: 1,
        }),
      ],
      calls: [],
      librarySeries: library,
      lookup: () => ({
        records: [candidate({ cv_volume_id: 4050_8888, name: 'Driftwood' })],
        complete: true,
        truncated: false,
      }),
    };
    renderScreen(state);

    await user.click(await screen.findByTestId('search-51'));
    const panel = await screen.findByTestId('row-search-51');
    expect(within(panel).getByTestId('row-search-note-51')).toHaveTextContent(
      'Change this match',
    );
    await user.click(within(panel).getByRole('button', { name: 'Search' }));
    await user.click(await screen.findByTestId('cand-51-40508888'));

    await waitFor(() =>
      expect(state.calls.find((c) => c.path.endsWith('/51/add'))).toBeTruthy(),
    );
  });

  it('FRG-UI-039 — a degraded ComicVine walk (the budget-ceiling shape) shows the add screen’s honest note, and the row stays actionable', async () => {
    const user = userEvent.setup();
    // A budget/upstream cut-off comes back as a part-way walk that returned
    // nothing (FRG-API-003 envelope) — classified by the SAME
    // `lookupOutcomeNote` the add screen uses, so the prose is identical.
    const state: FetcherState = {
      sources: [source],
      entitlements: [orphan],
      calls: [],
      librarySeries: library,
      lookup: () => ({ records: [], complete: false, truncated: false }),
    };
    renderScreen(state);

    await user.click(await screen.findByTestId('search-50'));
    await user.click(within(screen.getByTestId('row-search-50')).getByRole('button', { name: 'Search' }));

    expect(
      await screen.findByText(
        'ComicVine lookup failed part-way and returned nothing — try again in a moment.',
      ),
    ).toBeInTheDocument();
    // Still actionable later: the search, and the row, are both still there.
    expect(screen.getByTestId('row-search-input-50')).toBeEnabled();
    expect(screen.getByTestId('ignore-50')).toBeInTheDocument();
  });

  it('FRG-UI-039 — a ComicVine credential failure renders the same Settings guidance as the add screen', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: [orphan],
      calls: [],
      librarySeries: library,
      lookup: () => {
        throw new ApiRequestError(
          503,
          {
            message: 'comicvine lookup failed: ComicVine rejected the API key',
            errors: [
              {
                field: 'comicvine_api_key',
                message: 'ComicVine rejected the API key (missing or invalid)',
              },
            ],
          },
          '/api/v1/series/lookup?term=x',
        );
      },
    };
    renderScreen(state);

    await user.click(await screen.findByTestId('search-50'));
    await user.click(within(screen.getByTestId('row-search-50')).getByRole('button', { name: 'Search' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('ComicVine API key missing or invalid');
    expect(within(alert).getByRole('link', { name: 'check Settings' })).toHaveAttribute(
      'href',
      '/settings/general',
    );
  });
});

/*
 * FRG-UI-029 (MODIFIED) — thousand-row rendering: the review list virtualizes,
 * so a first-sync-scale corpus (a few thousand entitlements) puts only a window
 * of rows in the DOM, and the M4 shift-range selection still spans rows the window has
 * scrolled past (selection is id/index based over the filtered list, never
 * DOM-based).
 */
describe('FRG-UI-029: virtualized review list at corpus scale', () => {
  const source = makeSource({ id: 5, connection_state: 'connected' });
  /** A first-sync-scale corpus: far more rows than any window can hold. */
  const CORPUS = 1200;
  const corpus = Array.from({ length: CORPUS }, (_, i) =>
    ent({ id: 1000 + i, human_name: `Corpus Item ${i}` }),
  );

  /** Scroll the virtualized viewport to `offset` px and let it re-window. */
  function scrollTo(offset: number) {
    const scroller = screen.getByTestId('entitlement-scroller');
    Object.defineProperty(scroller, 'scrollTop', {
      value: offset,
      configurable: true,
    });
    fireEvent.scroll(scroller);
  }

  it('FRG-UI-029 — a 1,200-row queue renders only a window of rows', async () => {
    renderScreen({ sources: [source], entitlements: corpus, calls: [] });

    const list = await screen.findByTestId('entitlement-list');
    // Every row is counted (the count line and the scroll height are honest)…
    expect(list).toHaveAttribute('data-total-rows', String(CORPUS));
    expect(screen.getByTestId('count-line')).toHaveTextContent(
      `${CORPUS} items`,
    );
    // …but only a window of them is mounted.
    const rendered = screen.getAllByTestId(/^entitlement-row-/);
    expect(rendered.length).toBeGreaterThan(0);
    expect(rendered.length).toBeLessThan(80);
    // The window is the TOP of the list before any scrolling.
    expect(screen.getByTestId('entitlement-row-1000')).toBeInTheDocument();
    expect(screen.queryByTestId('entitlement-row-1300')).toBeNull();
  });

  it('FRG-UI-029 — shift-range selection spans rows across a scroll of the virtualized list', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: corpus,
      calls: [],
    };
    renderScreen(state);

    // Anchor on the first row, then scroll far enough that it unmounts.
    await user.click(await screen.findByTestId('select-1000'));
    scrollTo(3900);
    await waitFor(() => expect(screen.queryByTestId('select-1000')).toBeNull());

    const target = await screen.findByTestId('select-1050');
    await user.keyboard('{Shift>}');
    await user.click(target);
    await user.keyboard('{/Shift}');

    // Rows 1000..1050 inclusive — the span, not just the two mounted ends.
    const bar = await screen.findByTestId('bulk-bar');
    expect(bar).toHaveTextContent('51 selected');

    await user.click(screen.getByTestId('bulk-ignore'));
    await waitFor(() =>
      expect(
        state.calls.find((c) => c.path === '/api/v1/sources/entitlements/bulk'),
      ).toBeTruthy(),
    );
    const body = state.calls.find((c) => c.path.endsWith('/bulk'))!.init!.body as {
      entitlement_ids: number[];
    };
    expect(body.entitlement_ids).toHaveLength(51);
    expect(body.entitlement_ids).toContain(1000);
    expect(body.entitlement_ids).toContain(1050);
  });

  it('FRG-UI-039 — an open row search survives the row scrolling out of the window and back', async () => {
    const user = userEvent.setup();
    renderScreen({
      sources: [source],
      entitlements: corpus,
      calls: [],
      reads: [],
    });

    // Open the search on a row near the top of the list.
    await user.click(await screen.findByTestId('search-1000'));
    expect(await screen.findByTestId('row-search-1000')).toBeInTheDocument();

    // Scroll far enough that the row unmounts — the panel goes with it, since
    // only the WINDOW is in the DOM…
    scrollTo(3900);
    await waitFor(() => expect(screen.queryByTestId('search-1000')).toBeNull());
    expect(screen.queryByTestId('row-search-1000')).toBeNull();

    // …and scrolling back re-mounts the row with its search STILL OPEN: the
    // disclosure is list-owned, so scrolling past a row never cancels the task
    // the operator started on it.
    scrollTo(0);
    expect(await screen.findByTestId('row-search-1000')).toBeInTheDocument();
    expect(screen.getByTestId('search-1000')).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });
});

/*
 * FRG-UI-029 (MODIFIED) — same-title collapse: a run of rows sharing the
 * server's group_key folds into ONE expandable group with a count and its
 * members' status counts. Collapse is presentation, never a state filter:
 * every member's actions are one expand away, the header selects the whole
 * group, and a shift-range across a collapsed header still takes its rows.
 */
describe('FRG-UI-029: same-title collapse groups', () => {
  const source = makeSource({ id: 5, connection_state: 'connected' });

  /** Four Ember rows the server folded to one key, plus an unrelated row. */
  function emberCorpus(): EntitlementResource[] {
    return [
      ent({ id: 60, human_name: 'Ember, Vol. 1', group_key: 'ember' }),
      ent({ id: 61, human_name: 'Ember, Vol. 2', group_key: 'ember' }),
      ent({
        id: 62,
        human_name: 'Ember, Vol. 3',
        group_key: 'ember',
        review_status: 'matched',
        matched_series_id: 1,
      }),
      ent({
        id: 63,
        human_name: 'Ember, Vol. 4',
        group_key: 'ember',
        download_state: 'failed',
        download_error: 'md5 mismatch',
      }),
      ent({ id: 70, human_name: 'Driftwood, Vol. 1' }),
    ];
  }

  it('FRG-UI-029 — a run of 3+ same-title rows collapses into one group with a count, and a pair does not', async () => {
    renderScreen({
      sources: [source],
      entitlements: [
        ...emberCorpus(),
        // A two-row run stays below the collapse threshold — no header, and
        // both rows render plainly.
        ent({ id: 80, human_name: 'Vane, Vol. 1', group_key: 'vane' }),
        ent({ id: 81, human_name: 'Vane, Vol. 2', group_key: 'vane' }),
      ],
      calls: [],
    });

    const header = await screen.findByTestId('group-header-ember');
    expect(header).toHaveAttribute('data-collapsed', 'true');
    expect(screen.getByTestId('group-count-ember')).toHaveTextContent('4 items');
    // The group's title is the members' shared prefix.
    expect(within(header).getByText('Ember')).toBeInTheDocument();

    // Collapsed: the member rows are not rendered…
    expect(screen.queryByTestId('entitlement-row-60')).toBeNull();
    expect(screen.queryByTestId('entitlement-row-63')).toBeNull();
    // …while everything outside the group still is, including the sub-threshold
    // pair and the count line, which counts ROWS, never groups.
    expect(screen.getByTestId('entitlement-row-70')).toBeInTheDocument();
    expect(screen.getByTestId('entitlement-row-80')).toBeInTheDocument();
    expect(screen.getByTestId('entitlement-row-81')).toBeInTheDocument();
    expect(screen.queryByTestId('group-header-vane')).toBeNull();
    expect(screen.getByTestId('count-line')).toHaveTextContent('7 items');
  });

  it('FRG-UI-029 — a mixed-status group surfaces its counts (incl. a failed download) on the header', async () => {
    renderScreen({ sources: [source], entitlements: emberCorpus(), calls: [] });

    const statuses = await screen.findByTestId('group-statuses-ember');
    // Three new + one matched, and the failed download is called out — the
    // collapse hides no actionable state.
    expect(statuses).toHaveTextContent('3 new');
    expect(statuses).toHaveTextContent('1 matched');
    expect(statuses).toHaveTextContent('1 failed download');
  });

  it('FRG-UI-029 — expanding a group reaches every member row and its full actions', async () => {
    const user = userEvent.setup();
    renderScreen({ sources: [source], entitlements: emberCorpus(), calls: [] });

    await user.click(await screen.findByTestId('group-toggle-ember'));

    expect(screen.getByTestId('group-header-ember')).toHaveAttribute(
      'data-collapsed',
      'false',
    );
    for (const id of [60, 61, 62, 63]) {
      expect(screen.getByTestId(`entitlement-row-${id}`)).toBeInTheDocument();
      // The ever-present row search (FRG-UI-039) and the expand caret.
      expect(screen.getByTestId(`search-${id}`)).toBeInTheDocument();
      expect(screen.getByTestId(`expand-${id}`)).toBeInTheDocument();
    }
    // Per-status actions: the new rows offer Ignore, the matched one Change…,
    // and the failed one its Retry.
    expect(screen.getByTestId('ignore-60')).toBeInTheDocument();
    expect(screen.getByTestId('search-62')).toHaveTextContent('Change…');
    expect(screen.getByTestId('retry-63')).toBeInTheDocument();
  });

  it('FRG-UI-029 — the group header checkbox selects the whole group, collapsed and all', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: emberCorpus(),
      calls: [],
    };
    renderScreen(state);

    await user.click(await screen.findByTestId('group-select-ember'));
    expect(await screen.findByTestId('bulk-bar')).toHaveTextContent('4 selected');

    // It toggles as a unit: a second click clears the whole group…
    await user.click(screen.getByTestId('group-select-ember'));
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('0 selected');
    await user.click(screen.getByTestId('group-select-ember'));
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('4 selected');

    // …and the whole group is what the bulk action then receives.
    await user.click(screen.getByTestId('bulk-ignore'));
    await waitFor(() =>
      expect(state.calls.find((c) => c.path.endsWith('/bulk'))).toBeTruthy(),
    );
    const body = state.calls.find((c) => c.path.endsWith('/bulk'))!.init!.body as {
      entitlement_ids: number[];
    };
    expect([...body.entitlement_ids].sort((a, b) => a - b)).toEqual([
      60, 61, 62, 63,
    ]);
  });

  it('FRG-UI-029 — shift-range stays index-coherent across a collapsed group header', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: [
        ent({ id: 59, human_name: 'Before The Group' }),
        ...emberCorpus().slice(0, 4),
        ent({ id: 70, human_name: 'Driftwood, Vol. 1' }),
      ],
      calls: [],
    };
    renderScreen(state);

    // Anchor before the group, shift-click after it: the span crosses the
    // header, which stands for the four rows folded inside it.
    await user.click(await screen.findByTestId('select-59'));
    await user.keyboard('{Shift>}');
    await user.click(screen.getByTestId('select-70'));
    await user.keyboard('{/Shift}');

    expect(await screen.findByTestId('bulk-bar')).toHaveTextContent('6 selected');

    await user.click(screen.getByTestId('bulk-ignore'));
    await waitFor(() =>
      expect(state.calls.find((c) => c.path.endsWith('/bulk'))).toBeTruthy(),
    );
    const body = state.calls.find((c) => c.path.endsWith('/bulk'))!.init!.body as {
      entitlement_ids: number[];
    };
    expect([...body.entitlement_ids].sort((a, b) => a - b)).toEqual([
      59, 60, 61, 62, 63, 70,
    ]);
  });

  it('FRG-UI-025 — collapsing a group re-points an anchor folded inside it at the group header', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: [...emberCorpus().slice(0, 4), ent({ id: 70, human_name: 'Driftwood, Vol. 1' })],
      calls: [],
    };
    renderScreen(state);

    // Expand the group and anchor on a row INSIDE it…
    await user.click(await screen.findByTestId('group-toggle-ember'));
    await user.click(screen.getByTestId('select-61'));
    // …then collapse it, folding the anchor row out of the list.
    await user.click(screen.getByTestId('group-toggle-ember'));
    expect(screen.queryByTestId('select-61')).toBeNull();

    // The shift-range still draws: the anchor moved to the header, which stands
    // for the whole group, so the span is header-through-target.
    await user.keyboard('{Shift>}');
    await user.click(screen.getByTestId('select-70'));
    await user.keyboard('{/Shift}');

    expect(await screen.findByTestId('bulk-bar')).toHaveTextContent('5 selected');
    await user.click(screen.getByTestId('bulk-ignore'));
    await waitFor(() =>
      expect(state.calls.find((c) => c.path.endsWith('/bulk'))).toBeTruthy(),
    );
    const body = state.calls.find((c) => c.path.endsWith('/bulk'))!.init!.body as {
      entitlement_ids: number[];
    };
    expect([...body.entitlement_ids].sort((a, b) => a - b)).toEqual([
      60, 61, 62, 63, 70,
    ]);
  });

  it('FRG-UI-025 — a shift-click with a vanished anchor selects and re-anchors, never deselects', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: [
        ent({ id: 200, human_name: 'Still New' }),
        ent({ id: 201, human_name: 'Ignored One', review_status: 'ignored' }),
        ent({ id: 202, human_name: 'Ignored Two', review_status: 'ignored' }),
      ],
      calls: [],
    };
    renderScreen(state);

    // Select an ignored row, then a new row — the ANCHOR ends up on the new one.
    await user.click(await screen.findByTestId('select-202'));
    await user.click(screen.getByTestId('select-200'));
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('2 selected');

    // Filtering to Ignored takes the anchor row out of the list entirely.
    await user.click(screen.getByTestId('filter-ignored'));
    expect(screen.queryByTestId('select-200')).toBeNull();

    // A shift-click with no anchor to span from SELECTS the clicked row and
    // re-anchors there — it must never degrade into a toggle that deselects the
    // row the operator was reaching towards.
    await user.keyboard('{Shift>}');
    await user.click(screen.getByTestId('select-202'));
    await user.keyboard('{/Shift}');
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('2 selected');

    // …and the re-anchor is real: the NEXT shift-click draws a span from it.
    await user.keyboard('{Shift>}');
    await user.click(screen.getByTestId('select-201'));
    await user.keyboard('{/Shift}');
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('3 selected');

    await user.click(screen.getByTestId('bulk-restore'));
    await waitFor(() =>
      expect(state.calls.find((c) => c.path.endsWith('/bulk'))).toBeTruthy(),
    );
    const body = state.calls.find((c) => c.path.endsWith('/bulk'))!.init!.body as {
      entitlement_ids: number[];
    };
    expect([...body.entitlement_ids].sort((a, b) => a - b)).toEqual([
      200, 201, 202,
    ]);
  });
});

/*
 * FRG-SRC-011 — bundle identity on the review surface: rows and groups name the
 * bundle they came from, the bulk bar can select a whole bundle, and "apply the
 * match to this lot" is ONE server-side bulk accept in which each row
 * contributes its own proposal (per-row errors, never a vetoed batch).
 */
describe('FRG-SRC-011: bundle display, bundle selection, and bulk accept', () => {
  const source = makeSource({ id: 5, connection_state: 'connected' });
  const BUNDLE = 'Humble Comics Bundle: Synthetic Firsts';

  const bundled = [
    ent({ id: 90, human_name: 'Vane, Vol. 1', bundle_human_name: BUNDLE }),
    ent({ id: 91, human_name: 'Deadly Class, Vol. 1', bundle_human_name: BUNDLE }),
    // Same bundle, but ignored — invisible under the "New" filter, so a
    // bundle selection made there must not reach it.
    ent({
      id: 92,
      human_name: 'Nailbiter, Vol. 1',
      review_status: 'ignored',
      bundle_human_name: BUNDLE,
    }),
    ent({
      id: 93,
      human_name: 'Driftwood, Vol. 1',
      bundle_human_name: 'Humble Comics Bundle: Driftwood',
    }),
  ];

  it('FRG-SRC-011 — a row names its bundle, and the group header names a shared one', async () => {
    renderScreen({
      sources: [source],
      entitlements: [
        ...bundled,
        ent({ id: 94, human_name: 'Ember, Vol. 1', group_key: 'ember', bundle_human_name: BUNDLE }),
        ent({ id: 95, human_name: 'Ember, Vol. 2', group_key: 'ember', bundle_human_name: BUNDLE }),
        ent({ id: 96, human_name: 'Ember, Vol. 3', group_key: 'ember', bundle_human_name: BUNDLE }),
      ],
      calls: [],
    });

    expect(await screen.findByTestId('bundle-90')).toHaveTextContent(BUNDLE);
    expect(screen.getByTestId('group-header-ember')).toHaveTextContent(BUNDLE);
  });

  it('FRG-SRC-011 — "Select bundle" selects exactly that bundle\'s VISIBLE rows', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: bundled,
      calls: [],
    };
    renderScreen(state);

    // Scope to New: the ignored row of the same bundle is out of view.
    await user.click(await screen.findByTestId('filter-new'));
    await user.click(screen.getByTestId('select-bundle'));
    await user.click(screen.getByTestId(`bundle-option-${BUNDLE}`));

    expect(await screen.findByTestId('bulk-bar')).toHaveTextContent('2 selected');

    await user.click(screen.getByTestId('bulk-ignore'));
    await waitFor(() =>
      expect(state.calls.find((c) => c.path.endsWith('/bulk'))).toBeTruthy(),
    );
    const body = state.calls.find((c) => c.path.endsWith('/bulk'))!.init!.body as {
      entitlement_ids: number[];
    };
    // The bundle's two visible rows — not its ignored row, not the other bundle.
    expect([...body.entitlement_ids].sort((a, b) => a - b)).toEqual([90, 91]);
  });

  it('FRG-SRC-011 — bulk accept is ONE request carrying the ids, with no shared series_id', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: [
        ent({
          id: 100,
          human_name: 'Vane, Vol. 1',
          proposed_series_id: 1,
          proposed_match: {
            kind: 'library',
            series_id: 1,
            cv_volume_id: null,
            title: 'Vane',
            year: 2012,
            confidence: 0.93,
          },
        }),
        ent({
          id: 101,
          human_name: 'Glasswing, Vol. 1',
          proposed_match: {
            kind: 'comicvine',
            series_id: null,
            cv_volume_id: 4050_1111,
            title: 'Glasswing',
            year: 2015,
            confidence: 0.88,
          },
        }),
      ],
      calls: [],
    };
    renderScreen(state);

    await user.click(await screen.findByTestId('select-100'));
    await user.keyboard('{Shift>}');
    await user.click(screen.getByTestId('select-101'));
    await user.keyboard('{/Shift}');
    await user.click(screen.getByTestId('bulk-accept'));

    await waitFor(() =>
      expect(state.calls.filter((c) => c.path.endsWith('/bulk'))).toHaveLength(1),
    );
    const call = state.calls.find((c) => c.path.endsWith('/bulk'))!;
    const body = call.init!.body as {
      action: string;
      entitlement_ids: number[];
      series_id?: number;
    };
    // Heterogeneous rows (one match, one add) in ONE accept — each applies its
    // own stored proposal, so the body carries no shared series_id.
    expect(body.action).toBe('accept');
    expect([...body.entitlement_ids].sort((a, b) => a - b)).toEqual([100, 101]);
    expect(body.series_id).toBeUndefined();
    // …and the per-row match endpoint was never touched (no client-side loop).
    expect(state.calls.some((c) => c.path.endsWith('/match'))).toBe(false);
  });

  it('FRG-SRC-011 — per-row accept failures are reported by name while the succeeded rows refresh', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: [
        ent({
          id: 110,
          human_name: 'Vane, Vol. 1',
          proposed_series_id: 1,
          proposed_match: {
            kind: 'library',
            series_id: 1,
            cv_volume_id: null,
            title: 'Vane',
            year: 2012,
            confidence: 0.93,
          },
        }),
        // The row the pass looked at and could not place: the server refuses it
        // per-row, the batch still applies the rest.
        ent({
          id: 111,
          human_name: 'Mystery Anthology',
          proposed_match: {
            verdict: 'no-plausible-match',
            universe: 'comicvine',
            candidates: [],
          },
        }),
      ],
      calls: [],
      bulkResult: (body) => {
        if (body.action !== 'accept') {
          return { applied: body.entitlement_ids.length, skipped: 0, errors: {} };
        }
        // The server applied 110 and refused 111 — model both.
        state.entitlements = state.entitlements.map((e) =>
          e.id === 110
            ? { ...e, review_status: 'matched' as const, matched_series_id: 1 }
            : e,
        );
        return {
          applied: 1,
          skipped: 1,
          errors: {
            '111': 'entitlement 111 has no proposed match to accept',
          },
        };
      },
    };
    renderScreen(state);

    await user.click(await screen.findByTestId('select-110'));
    await user.click(screen.getByTestId('select-111'));
    await user.click(screen.getByTestId('bulk-accept'));

    // The count of failures, expandable to the row names and the reasons.
    const toggle = await screen.findByTestId('bulk-errors-toggle');
    expect(toggle).toHaveTextContent('1 item could not be accepted');
    await user.click(toggle);
    const failure = await screen.findByTestId('bulk-error-111');
    expect(failure).toHaveTextContent('Mystery Anthology');
    expect(failure).toHaveTextContent('has no proposed match to accept');
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('Accepted 1 of 2.');

    // The succeeded row still refreshed — the failures never cost the batch.
    await waitFor(() =>
      expect(screen.getByTestId('entitlement-row-110')).toHaveAttribute(
        'data-status',
        'matched',
      ),
    );
    // …and the failure stays selected, so it is the operator's to-do list.
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('1 selected');
  });

  it('FRG-SRC-011 — a partial bulk IGNORE reports its per-row failure instead of reading as complete', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: [
        ent({ id: 130, human_name: 'Vane, Vol. 1' }),
        ent({ id: 131, human_name: 'Vanished Item' }),
      ],
      calls: [],
      bulkResult: (body) => {
        // The server ignored 130 and could not touch 131 — every action can
        // half-succeed, not just accept.
        state.entitlements = state.entitlements.map((e) =>
          e.id === 130 ? { ...e, review_status: 'ignored' as const } : e,
        );
        expect(body.action).toBe('ignore');
        return {
          applied: 1,
          skipped: 1,
          errors: { '131': 'entitlement 131 no longer exists' },
        };
      },
    };
    renderScreen(state);

    await user.click(await screen.findByTestId('select-130'));
    await user.click(screen.getByTestId('select-131'));
    await user.click(screen.getByTestId('bulk-ignore'));

    // The panel names the row and the reason, in the action's own words.
    const toggle = await screen.findByTestId('bulk-errors-toggle');
    expect(toggle).toHaveTextContent('1 item could not be ignored');
    await user.click(toggle);
    const failure = await screen.findByTestId('bulk-error-131');
    expect(failure).toHaveTextContent('Vanished Item');
    expect(failure).toHaveTextContent('no longer exists');
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('Ignored 1 of 2.');

    // The selection is NOT cleared out from under a partial result: the failed
    // row stays selected as the to-do list, while the succeeded row refreshes.
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('1 selected');
    await waitFor(() =>
      expect(screen.getByTestId('entitlement-row-130')).toHaveAttribute(
        'data-status',
        'ignored',
      ),
    );
  });
});

/*
 * FRG-SRC-010 — the three proposal shapes read differently: a candidate, a
 * stored "we looked and nothing fit" verdict marker, and a NULL (not computed
 * yet, e.g. deferred on the ComicVine budget ceiling). None of them is a dead
 * end — the row search is there in every case.
 */
describe('FRG-SRC-010: proposal verdict vs not-yet-computed', () => {
  const source = makeSource({ id: 5, connection_state: 'connected' });

  it('FRG-SRC-010 — a no-plausible-match verdict marker reads as a verdict, not as a proposal', async () => {
    renderScreen({
      sources: [source],
      entitlements: [
        ent({
          id: 120,
          human_name: 'Odd Curio',
          proposed_match: {
            verdict: 'no-plausible-match',
            universe: 'comicvine',
            candidates: [],
            auto: false,
          },
        }),
      ],
      calls: [],
    });

    const note = await screen.findByTestId('no-match-120');
    expect(note).toHaveTextContent('No plausible match');
    expect(note).toHaveAttribute('data-verdict', 'no-plausible-match');
    // No accept affordance was minted out of the marker…
    expect(screen.queryByTestId('match-120')).toBeNull();
    expect(screen.queryByTestId('add-120')).toBeNull();
    // …and the row is still fully actionable.
    expect(screen.getByTestId('search-120')).toBeInTheDocument();
  });

  it('FRG-SRC-010 — a null proposal says the match has not been computed yet', async () => {
    renderScreen({
      sources: [source],
      entitlements: [ent({ id: 121, human_name: 'Deferred Item', proposed_match: null })],
      calls: [],
    });

    const note = await screen.findByTestId('no-match-121');
    expect(note).toHaveTextContent('Match not computed yet');
    expect(note).toHaveAttribute('data-verdict', 'not-computed');
    expect(screen.getByTestId('search-121')).toBeInTheDocument();
  });
});

/*
 * FRG-UI-046 — publisher classification rules moved to a library-wide
 * Settings panel (see General.test.tsx); no per-source control renders here.
 */
describe('FRG-UI-046: no per-source publisher-rules control', () => {
  it('FRG-UI-046 — the manage view renders no publisher-rules control', async () => {
    const source = makeSource({ id: 5, connection_state: 'connected' });
    renderScreen({ sources: [source], entitlements: [], calls: [] });

    await screen.findByTestId('count-line');
    expect(screen.queryByTestId('publisher-rules')).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('publisher-rules-toggle'),
    ).not.toBeInTheDocument();
  });
});

/*
 * FRG-SRC-013 — the operator trigger for the bulk proposal recompute. The work
 * itself is background + budget-polite (backend-side); what the screen owes is
 * one honest button, a pending state that cannot be double-fired, and the
 * server's own words on both outcomes.
 */
describe('FRG-SRC-013: bulk proposal recompute trigger', () => {
  const source = makeSource({ id: 5, connection_state: 'connected' });

  it('FRG-SRC-013 — a connected source offers Recompute proposals and posts an empty body (markers stay off)', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: [ent({ id: 30 })],
      calls: [],
    };
    renderScreen(state);

    const button = await screen.findByTestId('recompute-proposals');
    expect(button).toHaveTextContent('Recompute proposals');

    await user.click(button);

    await waitFor(() =>
      expect(
        state.calls.find(
          (c) => c.path === '/api/v1/sources/5/recompute-proposals',
        ),
      ).toBeTruthy(),
    );
    const call = state.calls.find(
      (c) => c.path === '/api/v1/sources/5/recompute-proposals',
    )!;
    expect(call.init?.method).toBe('POST');
    // No `include_markers`: re-asking about every no-plausible-match row is
    // real ComicVine spend, and the default trigger never opts into it.
    expect(call.init?.body).toEqual({});
  });

  it('FRG-SRC-013 — a queued (202) recompute shows the background note', async () => {
    const user = userEvent.setup();
    renderScreen({ sources: [source], entitlements: [], calls: [] });

    await user.click(await screen.findByTestId('recompute-proposals'));

    const note = await screen.findByTestId('recompute-note');
    expect(note).toHaveTextContent('Recompute queued — running in the background.');
  });

  it('FRG-SRC-013 — the trigger is disabled while the enqueue is in flight', async () => {
    const user = userEvent.setup();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    renderScreen({
      sources: [source],
      entitlements: [],
      calls: [],
      recomputeGate: gate,
    });

    const button = await screen.findByTestId('recompute-proposals');
    await user.click(button);

    await waitFor(() => expect(button).toBeDisabled());
    expect(button).toHaveTextContent('Queueing…');

    await act(async () => {
      release();
      await gate;
    });
    await waitFor(() => expect(button).toBeEnabled());
  });

  it('FRG-SRC-013 — a 409 (no ComicVine key) surfaces the server message', async () => {
    const user = userEvent.setup();
    renderScreen({
      sources: [source],
      entitlements: [],
      calls: [],
      recomputeError: new ApiRequestError(
        409,
        {
          message:
            'no ComicVine API key is configured — set one before recomputing proposals',
          errors: [{ field: 'comicvine_api_key', message: 'not configured' }],
        },
        '/api/v1/sources/5/recompute-proposals',
      ),
    });

    await user.click(await screen.findByTestId('recompute-proposals'));

    const note = await screen.findByTestId('recompute-note');
    expect(note).toHaveTextContent(
      'no ComicVine API key is configured — set one before recomputing proposals',
    );
    // The refusal is an alert, not a quiet info line.
    expect(note).toHaveAttribute('role', 'alert');
  });
});

/**
 * FRG-UI-043 — the group-header search/match affordance: a collapsed group's
 * header offers a picker seeded with the group title, an in-library pick
 * matches the WHOLE group in one apply_to_group (series_id + every member id),
 * a new pick sends cv_volume_id (server adds once, proposes the rest), and the
 * list re-derives after so the swept proposals + matches render.
 */
describe('FRG-UI-043: group-header search/match', () => {
  const source = makeSource({ id: 5, connection_state: 'connected' });

  /** Three rows the server folded to one key — a collapsed group by default. */
  function widgetGroup(): EntitlementResource[] {
    return [
      ent({ id: 60, human_name: 'Widget Chronicles, Vol. 1', group_key: 'widget' }),
      ent({ id: 61, human_name: 'Widget Chronicles, Vol. 2', group_key: 'widget' }),
      ent({ id: 62, human_name: 'Widget Chronicles, Vol. 3', group_key: 'widget' }),
    ];
  }

  it('FRG-UI-043 — the collapsed group header offers a search/match picker seeded with the group title', async () => {
    renderScreen({ sources: [source], entitlements: widgetGroup(), calls: [] });

    const header = await screen.findByTestId('group-header-widget');
    expect(header).toHaveAttribute('data-collapsed', 'true');
    // The affordance sits on the header, beside select-all and the collapse toggle.
    const user = userEvent.setup();
    await user.click(within(header).getByTestId('group-search-widget'));

    const panel = await screen.findByTestId('row-search-group-widget');
    // Seeded with the group's server fold (the same term the ranker uses).
    expect(within(panel).getByTestId('row-search-input-group-widget')).toHaveValue(
      'widget',
    );
  });

  it('FRG-UI-043 — picking an in-library candidate applies_to_group with series_id + every member id, then the list re-derives', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: widgetGroup(),
      calls: [],
      // The library holds the picked volume (series id 1 -> cv_volume_id 40500001).
      librarySeries: [makeSeriesResource({ id: 1, title: 'Widget Chronicles' })],
      lookup: () => ({
        records: [candidate({ cv_volume_id: 4050_0001, name: 'Widget Chronicles', have_it: true })],
        complete: true,
        truncated: false,
      }),
      // Model the server matching every member so the post-invalidation refetch
      // shows the group as fully matched — proving the list re-derived.
      bulkResult: (body) => {
        state.entitlements = state.entitlements.map((e) =>
          body.entitlement_ids.includes(e.id)
            ? { ...e, review_status: 'matched' as const, matched_series_id: 1 }
            : e,
        );
        return { applied: body.entitlement_ids.length, skipped: 0, errors: {} };
      },
    };
    renderScreen(state);

    await user.click(await screen.findByTestId('group-search-widget'));
    await user.click(
      within(screen.getByTestId('row-search-group-widget')).getByRole('button', {
        name: 'Search',
      }),
    );
    await user.click(await screen.findByTestId('cand-group-widget-40500001'));

    await waitFor(() =>
      expect(state.calls.find((c) => c.path.endsWith('/bulk'))).toBeTruthy(),
    );
    const body = state.calls.find((c) => c.path.endsWith('/bulk'))!.init!.body as {
      action: string;
      entitlement_ids: number[];
      series_id?: number;
      cv_volume_id?: number;
    };
    expect(body.action).toBe('apply_to_group');
    expect(body.series_id).toBe(1);
    expect(body.cv_volume_id).toBeUndefined();
    expect([...body.entitlement_ids].sort((a, b) => a - b)).toEqual([60, 61, 62]);

    // The success invalidation re-derived the list: the group now reads matched.
    await waitFor(() =>
      expect(screen.getByTestId('group-statuses-widget')).toHaveTextContent(
        '3 matched',
      ),
    );
  });

  it('FRG-UI-043 — picking a new candidate applies_to_group with cv_volume_id (server adds once, proposes the rest)', async () => {
    const user = userEvent.setup();
    const state: FetcherState = {
      sources: [source],
      entitlements: widgetGroup(),
      calls: [],
      reads: [],
      librarySeries: [makeSeriesResource({ id: 1, title: 'Unrelated Series' })],
      lookup: () => ({
        // Not in the library — a brand-new ComicVine volume.
        records: [candidate({ cv_volume_id: 4050_7777, name: 'Widget Chronicles', have_it: false })],
        complete: true,
        truncated: false,
      }),
    };
    renderScreen(state);

    const entReads = () =>
      state.reads!.filter((p) => /\/sources\/5\/entitlements$/.test(p)).length;
    await screen.findByTestId('group-header-widget');
    const before = entReads();

    await user.click(screen.getByTestId('group-search-widget'));
    await user.click(
      within(screen.getByTestId('row-search-group-widget')).getByRole('button', {
        name: 'Search',
      }),
    );
    await user.click(await screen.findByTestId('cand-group-widget-40507777'));

    await waitFor(() =>
      expect(state.calls.find((c) => c.path.endsWith('/bulk'))).toBeTruthy(),
    );
    const body = state.calls.find((c) => c.path.endsWith('/bulk'))!.init!.body as {
      action: string;
      entitlement_ids: number[];
      series_id?: number;
      cv_volume_id?: number;
    };
    expect(body.action).toBe('apply_to_group');
    expect(body.cv_volume_id).toBe(4050_7777);
    expect(body.series_id).toBeUndefined();
    expect([...body.entitlement_ids].sort((a, b) => a - b)).toEqual([60, 61, 62]);

    // The bulk hook's success invalidation re-fetched the entitlements so the
    // swept proposals render.
    await waitFor(() => expect(entReads()).toBeGreaterThan(before));
    // The picker closes on a successful group apply.
    await waitFor(() =>
      expect(screen.queryByTestId('row-search-group-widget')).toBeNull(),
    );
  });
});
