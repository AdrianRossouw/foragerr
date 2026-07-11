import { useEffect, useRef, useState } from 'react';
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { queryKeys } from './queryKeys';
import { useFetcher, type Fetcher } from './fetcher';
import { toQueueItem } from './queue';
import { useDebouncedValue } from '../lib/useDebouncedValue';
import type {
  ApiPage,
  BlocklistBulkDeleteResult,
  BlocklistRecord,
  CollectionRecord,
  CollectionsResponse,
  CommandResource,
  ContainmentRangeInput,
  CreatorPage,
  CreatorProfileResource,
  CreatorResource,
  FormatProfileResource,
  HealthWarningItem,
  HistoryRecord,
  IssueFileDeleteResult,
  IssueResource,
  LogLevel,
  LogRecordResource,
  LookupResponse,
  PullEntryRecord,
  QueueItem,
  QueuePageResponse,
  ReleaseDecision,
  RootFolderResource,
  ScheduledTaskResource,
  Series,
  SeriesCreatePayload,
  SeriesCreatedResource,
  SeriesEditPayload,
  SeriesGroupEditOp,
  SeriesGroupResource,
  SeriesResource,
  SuggestResponse,
  SystemHealthComponent,
  SystemStatusResource,
  WantedIssueRecord,
} from './types';

/*
 * Data-access hooks (FRG-UI-001).
 *
 * Each hook registers its query under the mirroring key from queryKeys and
 * issues requests to the corresponding URL path. In tests the fetcher is
 * faked, so the assertions can prove "one request to the right path" without a
 * live backend.
 */

/** Backend page-size cap (FRG-API-006: pageSize le=200). */
export const MAX_PAGE_SIZE = 200;

/**
 * Walk every page of a paged endpoint and return the flattened records. The
 * backend returns an empty page past the end, so we stop once we have reached
 * totalRecords OR a page comes back empty (defensive against a drifting total).
 * `pageUrl` builds the request path for a 1-based page number.
 */
export async function fetchAllPages<T>(
  fetcher: Fetcher,
  pageUrl: (page: number) => string,
): Promise<T[]> {
  const records: T[] = [];
  for (let page = 1; ; page += 1) {
    const res = await fetcher<ApiPage<T>>(pageUrl(page));
    records.push(...res.records);
    if (records.length >= res.totalRecords || res.records.length === 0) {
      return records;
    }
  }
}

export function useSeriesList(): UseQueryResult<Series[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.series.all(),
    queryFn: () => fetcher<Series[]>('/api/v1/series'),
  });
}

/**
 * Full library index under ['series'] (FRG-UI-003). The backend caps pageSize
 * at 200, so the queryFn walks pages until totalRecords is reached and
 * returns the flattened records — one cache entry for the whole library.
 * Supersedes the scaffold's `useSeriesList` (same key; never co-mounted).
 */
export function useSeriesIndex(): UseQueryResult<SeriesResource[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.series.all(),
    queryFn: () =>
      fetchAllPages<SeriesResource>(
        fetcher,
        (page) =>
          `/api/v1/series?page=${page}&pageSize=${MAX_PAGE_SIZE}&sortKey=sort_title&sortDirection=asc`,
      ),
  });
}

/**
 * Franchise grouping projection under ['series','groups'] (FRG-UI-021 /
 * FRG-API-020). Walks the paged aggregate endpoint like `useSeriesIndex`
 * (ungrouped series ride along as singleton franchises, so the list is total
 * and can exceed one 200-record page). `enabled` gates the fetch so the flat
 * views pay nothing for it while grouping is toggled off.
 */
export function useSeriesGroups(
  enabled = true,
): UseQueryResult<SeriesGroupResource[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.series.groups(),
    queryFn: () =>
      fetchAllPages<SeriesGroupResource>(
        fetcher,
        (page) =>
          `/api/v1/series/groups?page=${page}&pageSize=${MAX_PAGE_SIZE}&sortKey=title&sortDirection=asc`,
      ),
    enabled,
  });
}

export function useSeriesDetail(id: number): UseQueryResult<SeriesResource> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.series.detail(id),
    queryFn: () => fetcher<SeriesResource>(`/api/v1/series/${id}`),
  });
}

/**
 * All issues of one series under ['issues', seriesId] (FRG-UI-004), walking
 * the paged endpoint like `useSeriesIndex` (long-running comics exceed one
 * 200-issue page). Default ordering_key sort = persisted reading order.
 *
 * `enabled` gates the fetch (default on): the containment dialog's issue
 * pickers depend on a target series the operator has not chosen yet, so it
 * mounts this hook against a not-yet-known series and keeps it dormant until a
 * target is picked — never firing a `seriesId=0` request.
 */
export function useIssues(
  seriesId: number,
  enabled = true,
): UseQueryResult<IssueResource[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.issues.forSeries(seriesId),
    queryFn: () =>
      fetchAllPages<IssueResource>(
        fetcher,
        (page) =>
          `/api/v1/issues?seriesId=${seriesId}&page=${page}&pageSize=${MAX_PAGE_SIZE}`,
      ),
    enabled,
  });
}

/**
 * Declared collections for one series under ['series', id, 'collections']
 * (FRG-UI-026 / FRG-API-022). For a single-issues run the records are the
 * trades that collect it; for a collected edition they are its own issues'
 * declared contents. Display-only — no wanted/monitor state rides here.
 */
export function useCollections(
  seriesId: number,
): UseQueryResult<CollectionRecord[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.series.collections(seriesId),
    queryFn: async () => {
      const body = await fetcher<CollectionsResponse>(
        `/api/v1/series/${seriesId}/collections`,
      );
      return body.records;
    },
  });
}

/**
 * PUT /api/v1/issues/{issueId}/collections (FRG-API-022) — declare/replace ALL
 * of a trade issue's collected ranges. An invalid range rejects with an
 * `ApiRequestError` the dialog surfaces verbatim. On success both the current
 * series' collections view and every open issues table (the target series'
 * collected-in chips) are stale — the affected series is not always the one on
 * screen — so the collections key plus the broad ['issues'] prefix refresh.
 */
export function useSaveContainment(
  seriesId: number,
): UseMutationResult<
  unknown,
  Error,
  { issueId: number; ranges: ContainmentRangeInput[] }
> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ issueId, ranges }) =>
      fetcher(`/api/v1/issues/${issueId}/collections`, {
        method: 'PUT',
        body: { ranges },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.series.collections(seriesId),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.issues.all() });
    },
  });
}

/**
 * DELETE /api/v1/issues/{issueId}/collections (FRG-API-022) — clear a trade
 * issue's declared ranges. Same staleness as the declare path.
 */
export function useDeleteContainment(
  seriesId: number,
): UseMutationResult<unknown, Error, number> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (issueId: number) =>
      fetcher(`/api/v1/issues/${issueId}/collections`, { method: 'DELETE' }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.series.collections(seriesId),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.issues.all() });
    },
  });
}

/**
 * Live ComicVine lookup (FRG-UI-005); only fires for a non-empty term. The
 * backend returns a `LookupResponse` envelope (FRG-API-003) so the screen can
 * distinguish a degraded walk (`complete=false`) and a capped result set
 * (`truncated=true`) from a clean empty result. An upstream/credential failure
 * rejects with an `ApiRequestError`; screens classify credential failures
 * structurally via `isComicVineAuthError`.
 */
export function useLookup(term: string): UseQueryResult<LookupResponse> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.lookup.term(term),
    queryFn: () =>
      fetcher<LookupResponse>(
        `/api/v1/series/lookup?term=${encodeURIComponent(term)}`,
      ),
    enabled: term.length > 0,
    // A complete, uncapped candidate list is stable within a session; never
    // refetch such a ComicVine search behind the user's back (live,
    // rate-limited upstream). Degraded or capped outcomes stay immediately
    // stale so a re-submitted term retries for real instead of serving the
    // bad envelope from cache (errors carry no data, so the error case is
    // handled by the screen's explicit same-term refetch).
    staleTime: (query) =>
      query.state.data?.complete && !query.state.data.truncated ? Infinity : 0,
    retry: false,
  });
}

/** Add Series autosuggest debounce interval (FRG-UI-005 design decision #5). */
export const SUGGEST_DEBOUNCE_MS = 250;
/** Minimum trimmed-term length before an autosuggest request fires (FRG-UI-005). */
export const SUGGEST_MIN_TERM_LENGTH = 3;

/**
 * The suggest query result plus `settledTerm` — the debounced, trimmed term
 * the current `data`/`error` actually belong to. The dropdown lags the raw
 * input by the debounce, so a consumer that renders candidates under the live
 * input must gate on `settledTerm === input.trim()` to avoid painting a
 * superseded term's rows under a newer input during the debounce window
 * (FRG-UI-005).
 */
export type SuggestQueryResult = UseQueryResult<SuggestResponse> & {
  settledTerm: string;
};

/**
 * Bounded ComicVine suggest accelerator (FRG-API-017) backing the Add Series
 * autosuggest dropdown (FRG-UI-005). Takes the LIVE, per-keystroke typed term;
 * debounces it (~250ms) and gates on a >=3-char trimmed term before firing,
 * term-keyed under ['lookup','suggest',term] so a response for a superseded
 * term can never render over a newer one — the query for an old term simply
 * has no observer once the debounced term moves on. The query's AbortSignal
 * is wired through the fetcher so an in-flight request for a term that is no
 * longer current is also cancelled at the network layer, not just ignored.
 * `settledTerm` (the debounced term) is exposed so the screen can refuse to
 * render lagging candidates under a newer input.
 */
export function useSuggest(rawTerm: string): SuggestQueryResult {
  const fetcher = useFetcher();
  const debounced = useDebouncedValue(rawTerm.trim(), SUGGEST_DEBOUNCE_MS);
  const query = useQuery({
    queryKey: queryKeys.lookup.suggest(debounced),
    queryFn: ({ signal }) =>
      fetcher<SuggestResponse>(
        `/api/v1/series/lookup/suggest?term=${encodeURIComponent(debounced)}`,
        { signal },
      ),
    enabled: debounced.length >= SUGGEST_MIN_TERM_LENGTH,
    retry: false,
  });
  return { ...query, settledTerm: debounced } as SuggestQueryResult;
}

/** Configured root folders for the add-flow picker (FRG-UI-005). */
export function useRootFolders(): UseQueryResult<RootFolderResource[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.rootFolder.all(),
    queryFn: () => fetcher<RootFolderResource[]>('/api/v1/rootfolder'),
  });
}

/**
 * POST /api/v1/rootfolder — register a new root folder (FRG-SER-008). A
 * validation failure rejects with an `ApiRequestError` whose body carries the
 * backend's field-precise 400 verbatim; the settings screen renders that
 * message against the path input. On success the rootfolder list is invalidated.
 */
export function useCreateRootFolder(): UseMutationResult<
  RootFolderResource,
  Error,
  { path: string }
> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { path: string }) =>
      fetcher<RootFolderResource>('/api/v1/rootfolder', {
        method: 'POST',
        body,
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.rootFolder.all() }),
  });
}

/**
 * DELETE /api/v1/rootfolder/{id} — remove a root folder (FRG-SER-008). The
 * backend refuses (409) while any series references it, carrying the count in
 * its message; the caller surfaces that reason. On success the list refreshes.
 */
export function useDeleteRootFolder(): UseMutationResult<void, Error, number> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      fetcher<void>(`/api/v1/rootfolder/${id}`, { method: 'DELETE' }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.rootFolder.all() }),
  });
}

/** Format profiles for the add-flow picker (FRG-UI-005). */
export function useFormatProfiles(): UseQueryResult<FormatProfileResource[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.formatProfile.all(),
    queryFn: () => fetcher<FormatProfileResource[]>('/api/v1/formatprofile'),
  });
}

/**
 * Poll a command's status while it is live (FRG-UI-004/005: toolbar actions
 * and the add flow surface command progress). Stops polling once terminal.
 */
export function useCommandStatus(
  commandId: number | null,
): UseQueryResult<CommandResource> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.command.detail(commandId ?? -1),
    queryFn: () => fetcher<CommandResource>(`/api/v1/command/${commandId}`),
    enabled: commandId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === undefined || status === 'queued' || status === 'started'
        ? 2000
        : false;
    },
  });
}

/** Command lifecycle statuses that mean a watched command is still running. */
export const LIVE_COMMAND_STATUSES: ReadonlySet<string> = new Set([
  'queued',
  'started',
]);

/**
 * Watch one dispatched command: `start(id)` after the POST, a live status
 * while it runs, and `onFinished(terminalStatus)` exactly once when it reaches
 * a terminal status. Callers MUST branch on the status — a `failed` command
 * completed nothing, so success-only cache invalidations and "done" UI belong
 * behind a `status === 'completed'` check. The terminal status stays visible
 * (`status` is not reset) so chips can keep showing e.g. "completed"; a later
 * `start` watches the new command.
 *
 * `error` covers the WATCH path itself failing (the `GET /command/{id}` poll
 * erroring, as opposed to the command it is watching finishing with
 * `status: 'failed'`): without this, `status` would stay stuck at the
 * optimistic `'queued'` fallback forever (no data ever arrives to overwrite
 * it) and `running` would never clear, wedging the row's button disabled.
 * On a persistent poll error `status` becomes the synthetic terminal value
 * `'error'` (surfaced by the same chip that renders any other status) and
 * `running` clears like any other terminal transition; `error` carries the
 * message for a caller that wants to show more than the bare chip.
 */
export function useWatchedCommand(onFinished: (status: string) => void): {
  status: string | null;
  running: boolean;
  error: string | null;
  start: (commandId: number) => void;
} {
  const [commandId, setCommandId] = useState<number | null>(null);
  const commandQuery = useCommandStatus(commandId);
  const watchFailed = commandQuery.isError;
  const status = watchFailed
    ? 'error'
    : commandQuery.data?.status ?? (commandId !== null ? 'queued' : null);
  const running = status !== null && LIVE_COMMAND_STATUSES.has(status);
  const finished = status !== null && !running ? status : null;

  // Ref'd callback: the effect must fire once per terminal transition, not on
  // every render where the caller's inline closure gets a new identity.
  const onFinishedRef = useRef(onFinished);
  onFinishedRef.current = onFinished;
  useEffect(() => {
    if (!finished) return;
    onFinishedRef.current(finished);
  }, [finished]);

  return {
    status,
    running,
    error: watchFailed ? (commandQuery.error?.message ?? 'Could not check task status.') : null,
    start: setCommandId,
  };
}

/*
 * Real server-side pagination (FRG-UI-010/011/017 — design decision 5). One
 * shared paged-query hook over the standard envelope; History/Wanted/Blocklist
 * are thin wrappers. The queue's fixed-page-1 shortcut stays queue-only.
 */

/** Page size the daily surfaces request (well under the FRG-API-006 cap). */
export const SURFACE_PAGE_SIZE = 20;

const PAGED_FAMILIES = {
  history: queryKeys.history,
  wanted: queryKeys.wanted,
  blocklist: queryKeys.blocklist,
} as const;

export interface PagedQueryOptions {
  family: keyof typeof PAGED_FAMILIES;
  /** API path, e.g. '/api/v1/history'. */
  path: string;
  page: number;
  /** Server sort; omitted entirely to accept the endpoint's default order. */
  sortKey?: string;
  sortDirection?: 'asc' | 'desc';
  /** Filter query params; entries with an empty value are omitted. */
  filters?: Record<string, string>;
  /**
   * Clamp callback: invoked with the real last page when the fetched page is
   * empty but records still exist (the current page fell off the end because
   * its last rows were just removed). Screens wire this to their `setPage`.
   */
  onClampPage?: (page: number) => void;
}

/**
 * One page of a paged endpoint under the family-page key convention
 * (['history', page, filtersHash] — mirrors ['queue', page]). The previous
 * page's data is kept as placeholder while the next page loads so page
 * controls never flash a loading state mid-navigation.
 *
 * Page clamp: when a removal empties the final page, the server returns an
 * empty page for a page number now past the end (`records:[]`, `totalRecords>0`)
 * — which would otherwise render "Page N of N-1" over a false empty state. On
 * that exact signal the hook clamps back to the real last page via `onClampPage`
 * (a genuinely empty list stays on page 1 and shows its empty state).
 */
export function usePagedQuery<T>({
  family,
  path,
  page,
  sortKey,
  sortDirection = 'desc',
  filters,
  onClampPage,
}: PagedQueryOptions): UseQueryResult<ApiPage<T>> {
  const fetcher = useFetcher();
  const active = Object.entries(filters ?? {}).filter(([, value]) => value !== '');
  const filtersHash = active.map(([key, value]) => `${key}=${value}`).join('&');
  const params = new URLSearchParams([
    ['page', String(page)],
    ['pageSize', String(SURFACE_PAGE_SIZE)],
    ...(sortKey ? [['sortKey', sortKey], ['sortDirection', sortDirection]] : []),
    ...active,
  ]);
  const query = useQuery({
    queryKey: PAGED_FAMILIES[family].page(page, filtersHash),
    queryFn: () => fetcher<ApiPage<T>>(`${path}?${params.toString()}`),
    placeholderData: keepPreviousData,
  });

  // Clamp off the end. Act only on FRESH data for THIS page (never the
  // keepPreviousData placeholder of another page, guarded by data.page === page).
  const data = query.data;
  const isPlaceholder = query.isPlaceholderData;
  useEffect(() => {
    if (!onClampPage || !data || isPlaceholder) return;
    if (data.page !== page) return;
    if (data.records.length > 0 || page <= 1 || data.totalRecords <= 0) return;
    const lastPage = Math.max(1, Math.ceil(data.totalRecords / data.pageSize));
    if (lastPage < page) onClampPage(lastPage);
  }, [data, isPlaceholder, page, onClampPage]);

  return query;
}

/** GET /api/v1/history — paged pipeline events (FRG-UI-010 / FRG-API-011). */
export function useHistoryPage(
  page: number,
  filters: { eventType?: string; seriesId?: string } = {},
  onClampPage?: (page: number) => void,
): UseQueryResult<ApiPage<HistoryRecord>> {
  return usePagedQuery<HistoryRecord>({
    family: 'history',
    path: '/api/v1/history',
    page,
    sortKey: 'created_at',
    sortDirection: 'desc',
    filters: {
      eventType: filters.eventType ?? '',
      seriesId: filters.seriesId ?? '',
    },
    onClampPage,
  });
}

/** GET /api/v1/wanted/missing — the derived missing list (FRG-UI-011). */
export function useWantedPage(
  page: number,
  onClampPage?: (page: number) => void,
): UseQueryResult<ApiPage<WantedIssueRecord>> {
  return usePagedQuery<WantedIssueRecord>({
    family: 'wanted',
    path: '/api/v1/wanted/missing',
    page,
    onClampPage,
  });
}

/** Page size the Calendar requests — the endpoint's max (FRG-API-006 cap). */
const PULL_PAGE_SIZE = 200;

/**
 * GET /api/v1/pull?week= — the WHOLE ISO week for the Calendar (FRG-UI-018,
 * design decision 1). Day-grouping, banner counts, and the new-series strip are
 * all whole-week properties, so the hook aggregates every page (fetches at
 * pageSize=200 sorted by release_date and concatenates the remaining pages when
 * `totalRecords` exceeds one page) and returns the flat record list under one
 * key per week (`queryKeys.pull.week`). The endpoint stays read-only; per-entry
 * actions and the WebSocketBridge invalidate `queryKeys.pull.all()` so the whole
 * week re-derives.
 */
export function useWeeklyPull(
  week: string,
): UseQueryResult<PullEntryRecord[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.pull.week(week),
    queryFn: async () => {
      const pagePath = (page: number) =>
        `/api/v1/pull?week=${encodeURIComponent(week)}&page=${page}` +
        `&pageSize=${PULL_PAGE_SIZE}&sortKey=release_date&sortDirection=asc`;
      // Dedup by stable row id across pages. Aggregation is not atomic: if the
      // projection shifts between page fetches (a row's page changes as totals
      // move), a row could otherwise appear on two pages and produce two cards
      // with the same React key. Library-primary rows carry a null id (no stored
      // pull_entries row, so no stable identity) — those are never collapsed.
      const records: PullEntryRecord[] = [];
      const seenIds = new Set<number>();
      const absorb = (rows: PullEntryRecord[]): void => {
        for (const row of rows) {
          if (row.id != null) {
            if (seenIds.has(row.id)) continue;
            seenIds.add(row.id);
          }
          records.push(row);
        }
      };
      const first = await fetcher<ApiPage<PullEntryRecord>>(pagePath(1));
      absorb(first.records);
      const totalPages = Math.max(
        1,
        Math.ceil(first.totalRecords / PULL_PAGE_SIZE),
      );
      for (let page = 2; page <= totalPages; page += 1) {
        const next = await fetcher<ApiPage<PullEntryRecord>>(pagePath(page));
        absorb(next.records);
      }
      return records;
    },
  });
}

/** GET /api/v1/blocklist — paged banned releases (FRG-UI-017). */
export function useBlocklistPage(
  page: number,
  onClampPage?: (page: number) => void,
): UseQueryResult<ApiPage<BlocklistRecord>> {
  return usePagedQuery<BlocklistRecord>({
    family: 'blocklist',
    path: '/api/v1/blocklist',
    page,
    onClampPage,
  });
}

/** DELETE /api/v1/blocklist/{id} — the release becomes grabbable again. */
export function useRemoveBlocklistItem(): UseMutationResult<unknown, Error, number> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      fetcher(`/api/v1/blocklist/${id}`, { method: 'DELETE' }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.blocklist.all() }),
  });
}

/**
 * POST /api/v1/blocklist/delete {ids} — bulk removal. The response reports
 * partial failure ({deleted, missing}); the screen surfaces `missing` ids.
 */
export function useBulkRemoveBlocklist(): UseMutationResult<
  BlocklistBulkDeleteResult,
  Error,
  number[]
> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ids: number[]) =>
      fetcher<BlocklistBulkDeleteResult>('/api/v1/blocklist/delete', {
        method: 'POST',
        body: { ids },
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.blocklist.all() }),
  });
}

/** Page size the Logs screen requests (FRG-UI-024) — the pinned backend contract's default, well under the FRG-API-006 cap. */
export const LOG_PAGE_SIZE = 100;

/** Follow polling interval (FRG-UI-024 / design decision 2 — must be >= 2s). */
export const LOG_FOLLOW_INTERVAL_MS = 2_000;

/**
 * GET /api/v1/log (FRG-API-021 / FRG-UI-024) — the buffered, already-redacted
 * log ring, newest first. `level` is a MINIMUM-level filter and `logger` a
 * dotted-prefix filter; either is omitted from the request entirely when
 * empty (matching the pinned contract, not sent as `level=`/`logger=`).
 *
 * While `follow` is true the screen stays pinned to page 1 (design decision:
 * "Follow ON = stay on page 1 newest-first") regardless of what `page` the
 * caller passes, and the query polls every LOG_FOLLOW_INTERVAL_MS via
 * `refetchInterval`; `refetchIntervalInBackground: false` keeps a backgrounded
 * tab from polling. With `follow` false there is no `refetchInterval` at all,
 * and React Query stops any in-flight interval itself the moment `follow`
 * flips or the screen unmounts — no manual clearInterval bookkeeping needed.
 */
export function useLogPage({
  page,
  level,
  logger,
  follow,
}: {
  page: number;
  level?: LogLevel | '';
  logger?: string;
  follow: boolean;
}): UseQueryResult<ApiPage<LogRecordResource>> {
  const fetcher = useFetcher();
  const effectivePage = follow ? 1 : page;
  const params = new URLSearchParams([
    ['page', String(effectivePage)],
    ['pageSize', String(LOG_PAGE_SIZE)],
    ...(level ? [['level', level]] : []),
    ...(logger ? [['logger', logger]] : []),
  ]);
  const filtersHash = `level=${level ?? ''}&logger=${logger ?? ''}`;
  return useQuery({
    queryKey: queryKeys.log.page(effectivePage, filtersHash),
    queryFn: () =>
      fetcher<ApiPage<LogRecordResource>>(`/api/v1/log?${params.toString()}`),
    placeholderData: keepPreviousData,
    refetchInterval: follow ? LOG_FOLLOW_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });
}

/**
 * DELETE /api/v1/issuefile/{id} (FRG-UI-004): route one issue's file through
 * the recycle bin. The issue reverts to file-less, so series detail, its
 * issues, the wanted list, and history are all stale on success.
 */
export function useDeleteIssueFile(
  seriesId: number,
): UseMutationResult<IssueFileDeleteResult, Error, number> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (issueFileId: number) =>
      fetcher<IssueFileDeleteResult>(`/api/v1/issuefile/${issueFileId}`, {
        method: 'DELETE',
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.series.detail(seriesId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.issues.forSeries(seriesId),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.wanted.all() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.history.all() });
    },
  });
}

/**
 * Total tracked-download count for the sidebar Activity badge (FRG-UI-023).
 * Reads the EXISTING queue endpoint's paging envelope (`totalRecords`) with a
 * minimal page — no new API surface. Keyed under the ['queue'] prefix so the
 * WebSocketBridge's queue push (`queryKeys.queue.all()` invalidation) refreshes
 * it live; add/remove are the only events that change the count, and they emit
 * exactly that push. No polling timer.
 */
export function useQueueCount(): UseQueryResult<number> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.queue.count(),
    queryFn: async () => {
      const body = await fetcher<QueuePageResponse>('/api/v1/queue?page=1&pageSize=1');
      return body.totalRecords;
    },
  });
}

export function useQueuePage(page: number): UseQueryResult<QueueItem[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.queue.page(page),
    // The cached value is the NORMALIZED QueueItem[] (not the paging envelope):
    // the WebSocketBridge queue-progress patch maps over this exact shape.
    queryFn: async () => {
      const body = await fetcher<QueuePageResponse>(`/api/v1/queue?page=${page}`);
      return body.records.map(toQueueItem);
    },
  });
}

export function useReleases(issueId: number): UseQueryResult<ReleaseDecision[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.release.forIssue(issueId),
    queryFn: () => fetcher<ReleaseDecision[]>(`/api/v1/release?issueId=${issueId}`),
    // A live multi-indexer search is expensive server-side; never refire it on
    // focus/remount while an overlay session is open.
    staleTime: Infinity,
    retry: false,
  });
}

export interface RemoveQueueItemInput {
  id: number;
  /** Also instruct the download client to delete the downloaded data. */
  deleteData: boolean;
  /** Also blocklist the release so it is never grabbed again. */
  blocklist: boolean;
}

/** DELETE /api/v1/queue/{id}?blocklist=&deleteData= (FRG-UI-006). */
export function useRemoveQueueItem(): UseMutationResult<
  unknown,
  Error,
  RemoveQueueItemInput
> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, blocklist, deleteData }: RemoveQueueItemInput) =>
      fetcher(
        `/api/v1/queue/${id}?blocklist=${blocklist}&deleteData=${deleteData}`,
        { method: 'DELETE' },
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.queue.all() }),
  });
}

/** The (indexerId, guid) release-cache key, field names as the backend expects. */
export interface GrabReleaseInput {
  indexer_id: number;
  guid: string;
}

/**
 * POST /api/v1/release with a cached decision's key (FRG-UI-007). An expired
 * cache entry surfaces as an ApiRequestError with status 404 carrying the
 * backend's deterministic "search again" message verbatim.
 */
export function useGrabRelease(): UseMutationResult<unknown, Error, GrabReleaseInput> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (key: GrabReleaseInput) =>
      fetcher('/api/v1/release', { method: 'POST', body: key }),
    onSuccess: () =>
      // The grab enqueues a tracked download; the queue view is now stale.
      queryClient.invalidateQueries({ queryKey: queryKeys.queue.all() }),
  });
}

/*
 * Mutations. Each one writes the server's own response back into the cache
 * (setQueryData) and/or invalidates the mirroring list key — screens never
 * hand-roll refetches (FRG-UI-001).
 */

/** PUT /api/v1/series/{id} — persist series edits (monitored toggle, etc.). */
export function useUpdateSeries(
  seriesId: number,
): UseMutationResult<SeriesResource, Error, SeriesEditPayload> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: SeriesEditPayload) =>
      fetcher<SeriesResource>(`/api/v1/series/${seriesId}`, {
        method: 'PUT',
        body: payload,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.series.detail(seriesId), updated);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.series.all(),
        exact: true,
      });
    },
  });
}

/**
 * PUT /api/v1/series/{id} carrying only a grouping override op (FRG-SER-017 /
 * FRG-UI-021): rename a franchise group, or reassign/detach/unlock a series.
 * Rename applies to the group ANY member series belongs to, so the caller
 * passes a member's `seriesId`. On success the flat index (each row's
 * `series_group_id`), that series' detail, and the grouping projection are all
 * stale, so all three keys are refreshed.
 */
export function useUpdateSeriesGroup(): UseMutationResult<
  SeriesResource,
  Error,
  { seriesId: number; group: SeriesGroupEditOp }
> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ seriesId, group }) =>
      fetcher<SeriesResource>(`/api/v1/series/${seriesId}`, {
        method: 'PUT',
        body: { group },
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.series.detail(updated.id), updated);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.series.all(),
        exact: true,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.series.groups() });
    },
  });
}

/**
 * DELETE /api/v1/series/{id}?deleteFiles= — remove a series (FRG-UI-004).
 *
 * Two backend shapes (m2-daily-surfaces):
 *   - plain delete (deleteFiles=false) → 204, resolves `null`;
 *   - deleteFiles=true → 202 with the enqueued `delete-series-files`
 *     CommandResource, resolved here so the caller can WATCH it and reflect its
 *     status (the files are removed asynchronously by that command).
 *
 * The series row and its missing Wanted issues are gone the moment either
 * request returns, so the list/detail/wanted caches are refreshed on success.
 * The deleteFiles command's file_deleted HISTORY rows land only when it reaches
 * terminal — the caller re-invalidates history/wanted then (and the WS
 * history/wanted pushes cover any observer that has already navigated away).
 */
export function useDeleteSeries(): UseMutationResult<
  CommandResource | null,
  Error,
  { seriesId: number; deleteFiles: boolean }
> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ seriesId, deleteFiles }) =>
      fetcher<CommandResource | null>(
        `/api/v1/series/${seriesId}?deleteFiles=${deleteFiles}`,
        { method: 'DELETE' },
      ),
    onSuccess: (_data, { seriesId }) => {
      queryClient.removeQueries({ queryKey: queryKeys.series.detail(seriesId) });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.series.all(),
        exact: true,
      });
      // The grouped projection is a sibling key (['series','groups']) the
      // exact ['series'] invalidation above does NOT touch — refresh it too so
      // a franchise view reflects the removed run (and any pruned group).
      void queryClient.invalidateQueries({ queryKey: queryKeys.series.groups() });
      // The series' missing issues leave Wanted immediately; history's
      // file_deleted rows follow the delete-series-files command's completion.
      void queryClient.invalidateQueries({ queryKey: queryKeys.wanted.all() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.history.all() });
    },
  });
}

/** POST /api/v1/series — add a series with its write-only options. */
export function useAddSeries(): UseMutationResult<
  SeriesCreatedResource,
  Error,
  SeriesCreatePayload
> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: SeriesCreatePayload) =>
      fetcher<SeriesCreatedResource>('/api/v1/series', {
        method: 'POST',
        body: payload,
      }),
    onSuccess: (created) => {
      queryClient.setQueryData(queryKeys.series.detail(created.id), created);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.series.all(),
        exact: true,
      });
      // The new series joins a franchise (or rides along as a singleton), so
      // the grouped projection sibling key is stale too — refresh it.
      void queryClient.invalidateQueries({ queryKey: queryKeys.series.groups() });
    },
  });
}

/** Patch one issue row inside the ['issues', seriesId] cache entry. */
function patchIssueRows(
  rows: IssueResource[] | undefined,
  ids: readonly number[],
  monitored: boolean,
): IssueResource[] | undefined {
  return rows?.map((row) =>
    ids.includes(row.id) ? { ...row, monitored } : row,
  );
}

/** PUT /api/v1/issues/{id} — single-issue monitored toggle (FRG-UI-004). */
export function useSetIssueMonitored(
  seriesId: number,
): UseMutationResult<IssueResource, Error, { issueId: number; monitored: boolean }> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ issueId, monitored }) =>
      fetcher<IssueResource>(`/api/v1/issues/${issueId}`, {
        method: 'PUT',
        body: { monitored },
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData<IssueResource[]>(
        queryKeys.issues.forSeries(seriesId),
        (rows) => patchIssueRows(rows, [updated.id], updated.monitored),
      );
    },
  });
}

/**
 * PUT /api/v1/issues/{id} — single-issue monitored toggle used by the Calendar
 * (FRG-PULL-007). Unlike `useSetIssueMonitored`, it is not scoped to a series'
 * issues table: it delegates to the canonical issue endpoint and invalidates the
 * DERIVED views (pull + wanted + any open issues table) so the pull card's
 * projected state and the Wanted list re-derive. It writes no pull-side status
 * (D4) — the card changes only because the issue projection changed.
 */
export function useToggleIssueMonitored(): UseMutationResult<
  IssueResource,
  Error,
  { issueId: number; monitored: boolean }
> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ issueId, monitored }) =>
      fetcher<IssueResource>(`/api/v1/issues/${issueId}`, {
        method: 'PUT',
        body: { monitored },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.pull.all() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.wanted.all() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.issues.all() });
    },
  });
}

/** PUT /api/v1/issues/monitor — atomic bulk monitored toggle (FRG-UI-004). */
export function useBulkSetIssuesMonitored(
  seriesId: number,
): UseMutationResult<
  { issue_ids: number[]; monitored: boolean },
  Error,
  { issueIds: number[]; monitored: boolean }
> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ issueIds, monitored }) =>
      fetcher<{ issue_ids: number[]; monitored: boolean }>(
        '/api/v1/issues/monitor',
        { method: 'PUT', body: { issue_ids: issueIds, monitored } },
      ),
    onSuccess: (result) => {
      queryClient.setQueryData<IssueResource[]>(
        queryKeys.issues.forSeries(seriesId),
        (rows) => patchIssueRows(rows, result.issue_ids, result.monitored),
      );
    },
  });
}

/**
 * POST /api/v1/command — dispatch a backbone command (refresh-series,
 * scan-series, series-search, issue-search). Returns the CommandResource so
 * callers can track status via `useCommandStatus`.
 */
export function useRunCommand(): UseMutationResult<
  CommandResource,
  Error,
  { name: string; payload?: Record<string, unknown> }
> {
  const fetcher = useFetcher();
  return useMutation({
    mutationFn: ({ name, payload }) =>
      fetcher<CommandResource>('/api/v1/command', {
        method: 'POST',
        body: { name, payload: payload ?? null },
      }),
  });
}

/*
 * System area (FRG-UI-016): status, health, and scheduled-task hooks over
 * FRG-API-014 / FRG-NFR-011. The backend routers land from a parallel change
 * area; these hooks are coded directly from the delta specs' contracts.
 */

/**
 * GET /api/v1/system/status (FRG-API-014): version/build, managed `/config`
 * paths, and runtime info — never a secret. Plain fetch-once; nothing here
 * changes without a restart.
 */
export function useSystemStatus(): UseQueryResult<SystemStatusResource> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.system.status(),
    queryFn: () => fetcher<SystemStatusResource>('/api/v1/system/status'),
  });
}

/**
 * Poll interval for the System Health screen (design decision 7): health is
 * low-frequency, so a modest refetch is enough for a recovered component to
 * clear without a manual refresh or restart.
 */
export const HEALTH_POLL_INTERVAL_MS = 15_000;

/**
 * GET /api/v1/health (FRG-API-014) — the actionable warnings list, distinct
 * from the root liveness `/health` probe. Poll-first per design decision 7.
 */
export function useHealthWarnings(): UseQueryResult<HealthWarningItem[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.health.warnings(),
    queryFn: () => fetcher<HealthWarningItem[]>('/api/v1/health'),
    refetchInterval: HEALTH_POLL_INTERVAL_MS,
  });
}

/**
 * GET /api/v1/system/health (FRG-NFR-011) — the full per-component health
 * table. Poll-first alongside the warnings list so both halves of the Health
 * screen recover together.
 */
export function useSystemHealth(): UseQueryResult<SystemHealthComponent[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.system.health(),
    queryFn: () => fetcher<SystemHealthComponent[]>('/api/v1/system/health'),
    refetchInterval: HEALTH_POLL_INTERVAL_MS,
  });
}

/** GET /api/v1/system/task (FRG-API-014) — scheduled tasks with schedule state and the command each runs. */
export function useSystemTasks(): UseQueryResult<ScheduledTaskResource[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.system.tasks(),
    queryFn: () => fetcher<ScheduledTaskResource[]>('/api/v1/system/task'),
  });
}

/**
 * POST /api/v1/system/task/{name} (FRG-API-014 / FRG-SCHED-007) — force-run a
 * scheduled task: enqueues now, resets the timer, dedups, and returns the
 * enqueued command so the caller can watch it to terminal via
 * `useWatchedCommand`. "Back up now" is this mutation against the
 * `backup-database` task name. The task list is invalidated immediately (the
 * timer reset is visible right away); the caller re-invalidates once the
 * watched command reaches terminal so last-run/next-run reflect the finished
 * run too.
 */
export function useForceRunTask(): UseMutationResult<CommandResource, Error, string> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    // Defensive: task names are registry slugs today (no reserved URL
    // characters), but the name still rides straight into a path segment.
    mutationFn: (name: string) =>
      fetcher<CommandResource>(`/api/v1/system/task/${encodeURIComponent(name)}`, {
        method: 'POST',
      }),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.system.tasks() }),
  });
}

/*
 * Creators surface (FRG-UI-027/028 / FRG-API-023). Read hooks over the paged
 * grid + the profile aggregates, and the explicit-only follow toggle. All data
 * is library-derived (stored credits) — no ComicVine request is issued.
 */

/** Params for the creators grid / series-focused strip read. */
export interface CreatorsListParams {
  /** Followed-only filter (the header aggregates stay whole-library). */
  followed?: boolean;
  /** Focus the list on ONE series' creators (the series-detail strip target). */
  seriesId?: number;
  sortKey?: 'name' | 'seriesCount';
  sortDirection?: 'asc' | 'desc';
  /** Gate the fetch (e.g. the strip stays dormant for an unknown series id). */
  enabled?: boolean;
}

/** The flattened creators grid: every page's rows plus the header aggregates. */
export interface CreatorsListResult {
  records: CreatorResource[];
  totalCreators: number;
  followedCreators: number;
}

/**
 * GET /api/v1/creators — the creators grid (FRG-UI-027), also reused by the
 * series-detail strip (`seriesId` focus, FRG-UI-004). Walks pages like the
 * library index (a prolific library can exceed one 200-row page) and returns
 * the flat rows plus the whole-library header aggregates (read off the first
 * page's envelope). Each filter/focus/sort combination is its own cache entry.
 */
export function useCreatorsList(
  params: CreatorsListParams = {},
): UseQueryResult<CreatorsListResult> {
  const fetcher = useFetcher();
  const {
    followed,
    seriesId,
    sortKey = 'name',
    sortDirection = 'asc',
    enabled = true,
  } = params;
  const filters = new URLSearchParams();
  filters.set('sortKey', sortKey);
  filters.set('sortDirection', sortDirection);
  if (followed) filters.set('followed', 'true');
  if (seriesId != null) filters.set('seriesId', String(seriesId));
  const paramsHash = filters.toString();
  return useQuery({
    queryKey: queryKeys.creators.list(paramsHash),
    queryFn: async () => {
      const pagePath = (page: number) =>
        `/api/v1/creators?page=${page}&pageSize=${MAX_PAGE_SIZE}&${paramsHash}`;
      const first = await fetcher<CreatorPage>(pagePath(1));
      const records = [...first.records];
      const totalPages = Math.max(1, Math.ceil(first.totalRecords / MAX_PAGE_SIZE));
      for (let page = 2; page <= totalPages; page += 1) {
        const next = await fetcher<CreatorPage>(pagePath(page));
        records.push(...next.records);
      }
      return {
        records,
        totalCreators: first.totalCreators,
        followedCreators: first.followedCreators,
      };
    },
    enabled,
  });
}

/**
 * GET /api/v1/creators/{id} — the creator profile (FRG-UI-028). An unknown id
 * 404s (ApiRequestError, status 404) which the screen renders as its not-found
 * state; retries off so the 404 surfaces immediately.
 */
export function useCreatorProfile(
  creatorId: number,
): UseQueryResult<CreatorProfileResource> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.creators.detail(creatorId),
    queryFn: () =>
      fetcher<CreatorProfileResource>(`/api/v1/creators/${creatorId}`),
    enabled: Number.isFinite(creatorId) && creatorId > 0,
    retry: false,
  });
}

/** Toggle `followed` in one cached creators-list result (optimistic patch). */
function patchListFollow(
  data: CreatorsListResult | undefined,
  creatorId: number,
  followed: boolean,
): CreatorsListResult | undefined {
  if (!data) return data;
  let delta = 0;
  const records = data.records.map((row) => {
    if (row.id !== creatorId || row.followed === followed) return row;
    delta = followed ? 1 : -1;
    return { ...row, followed };
  });
  return {
    ...data,
    records,
    // Keep the header aggregate honest instantly; invalidation reconciles truth.
    followedCreators: Math.max(0, data.followedCreators + delta),
  };
}

/**
 * PUT /api/v1/creators/{id}/follow — the explicit-only follow toggle
 * (FRG-API-023 / FRG-CRTR-004): it is the ONLY follow entry point (the grid
 * pill and the profile button both call it). Optimistic — the pill flips
 * immediately across every loaded grid entry and the profile — with rollback on
 * failure (house mutation pattern); on settle it invalidates the whole
 * `['creators']` family so the list rows, header aggregates, and profile
 * re-derive from the server. Writes ONLY the flag (no series/issue/search
 * state), so the toggle is exactly one PUT and no other write.
 */
export function useSetCreatorFollow(): UseMutationResult<
  CreatorResource,
  Error,
  { creatorId: number; followed: boolean },
  { previous: [readonly unknown[], unknown][] }
> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ creatorId, followed }) =>
      fetcher<CreatorResource>(`/api/v1/creators/${creatorId}/follow`, {
        method: 'PUT',
        body: { followed },
      }),
    onMutate: async ({ creatorId, followed }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.creators.all() });
      const previous = queryClient.getQueriesData({
        queryKey: queryKeys.creators.all(),
      });
      for (const [key, value] of previous) {
        if (value && typeof value === 'object' && 'records' in value) {
          queryClient.setQueryData(
            key,
            patchListFollow(value as CreatorsListResult, creatorId, followed),
          );
        } else if (
          value &&
          typeof value === 'object' &&
          'stats' in value &&
          (value as CreatorProfileResource).id === creatorId
        ) {
          queryClient.setQueryData(key, {
            ...(value as CreatorProfileResource),
            followed,
          });
        }
      }
      return { previous };
    },
    onError: (_error, _vars, context) => {
      for (const [key, value] of context?.previous ?? []) {
        queryClient.setQueryData(key, value);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.creators.all() });
    },
  });
}
