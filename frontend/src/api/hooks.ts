import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { queryKeys } from './queryKeys';
import { useFetcher } from './fetcher';
import type { Series, SeriesDetail, QueueItem, ReleaseDecision } from './types';

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
    queryFn: () => fetcher<QueueItem[]>(`/api/v1/queue?page=${page}`),
  });
}

export function useReleases(issueId: number): UseQueryResult<ReleaseDecision[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.release.forIssue(issueId),
    queryFn: () => fetcher<ReleaseDecision[]>(`/api/v1/release?issueId=${issueId}`),
  });
}
