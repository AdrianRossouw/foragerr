import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { queryKeys } from './queryKeys';
import { useFetcher } from './fetcher';
import { toQueueItem } from './queue';
import type {
  Series,
  SeriesDetail,
  QueueItem,
  QueuePageResponse,
  ReleaseDecision,
} from './types';

/*
 * Data-access hooks (FRG-UI-001).
 *
 * Each hook registers its query under the mirroring key from queryKeys and issues
 * EXACTLY ONE request to the corresponding URL path. In tests the fetcher is
 * faked, so the assertions can prove "one request to the right path" without a
 * live backend.
 */

export function useSeriesList(): UseQueryResult<Series[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.series.all(),
    queryFn: () => fetcher<Series[]>('/api/v1/series'),
  });
}

export function useSeriesDetail(id: number): UseQueryResult<SeriesDetail> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.series.detail(id),
    queryFn: () => fetcher<SeriesDetail>(`/api/v1/series/${id}`),
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
