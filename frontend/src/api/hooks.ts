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
import type {
  ApiPage,
  BlocklistBulkDeleteResult,
  BlocklistRecord,
  CommandResource,
  FormatProfileResource,
  HistoryRecord,
  IssueFileDeleteResult,
  IssueResource,
  LookupResponse,
  QueueItem,
  QueuePageResponse,
  ReleaseDecision,
  RootFolderResource,
  Series,
  SeriesCreatePayload,
  SeriesCreatedResource,
  SeriesEditPayload,
  SeriesResource,
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
 */
export function useIssues(seriesId: number): UseQueryResult<IssueResource[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.issues.forSeries(seriesId),
    queryFn: () =>
      fetchAllPages<IssueResource>(
        fetcher,
        (page) =>
          `/api/v1/issues?seriesId=${seriesId}&page=${page}&pageSize=${MAX_PAGE_SIZE}`,
      ),
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
 */
export function useWatchedCommand(onFinished: (status: string) => void): {
  status: string | null;
  running: boolean;
  start: (commandId: number) => void;
} {
  const [commandId, setCommandId] = useState<number | null>(null);
  const commandQuery = useCommandStatus(commandId);
  const status = commandQuery.data?.status ?? (commandId !== null ? 'queued' : null);
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

  return { status, running, start: setCommandId };
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
}

/**
 * One page of a paged endpoint under the family-page key convention
 * (['history', page, filtersHash] — mirrors ['queue', page]). The previous
 * page's data is kept as placeholder while the next page loads so page
 * controls never flash a loading state mid-navigation.
 */
export function usePagedQuery<T>({
  family,
  path,
  page,
  sortKey,
  sortDirection = 'desc',
  filters,
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
  return useQuery({
    queryKey: PAGED_FAMILIES[family].page(page, filtersHash),
    queryFn: () => fetcher<ApiPage<T>>(`${path}?${params.toString()}`),
    placeholderData: keepPreviousData,
  });
}

/** GET /api/v1/history — paged pipeline events (FRG-UI-010 / FRG-API-011). */
export function useHistoryPage(
  page: number,
  filters: { eventType?: string; seriesId?: string } = {},
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
  });
}

/** GET /api/v1/wanted/missing — the derived missing list (FRG-UI-011). */
export function useWantedPage(
  page: number,
): UseQueryResult<ApiPage<WantedIssueRecord>> {
  return usePagedQuery<WantedIssueRecord>({
    family: 'wanted',
    path: '/api/v1/wanted/missing',
    page,
  });
}

/** GET /api/v1/blocklist — paged banned releases (FRG-UI-017). */
export function useBlocklistPage(
  page: number,
): UseQueryResult<ApiPage<BlocklistRecord>> {
  return usePagedQuery<BlocklistRecord>({
    family: 'blocklist',
    path: '/api/v1/blocklist',
    page,
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

/** DELETE /api/v1/series/{id}?deleteFiles= — remove a series (FRG-UI-004). */
export function useDeleteSeries(): UseMutationResult<
  void,
  Error,
  { seriesId: number; deleteFiles: boolean }
> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ seriesId, deleteFiles }) =>
      fetcher<void>(`/api/v1/series/${seriesId}?deleteFiles=${deleteFiles}`, {
        method: 'DELETE',
      }),
    onSuccess: (_data, { seriesId }) => {
      queryClient.removeQueries({ queryKey: queryKeys.series.detail(seriesId) });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.series.all(),
        exact: true,
      });
      // Deleting a series removes its missing issues from Wanted and (with
      // deleteFiles) writes file_deleted history rows (m2-daily-surfaces).
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
