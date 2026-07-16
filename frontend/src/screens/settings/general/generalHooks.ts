import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { queryKeys } from '../../../api/queryKeys';
import { useFetcher } from '../../../api/fetcher';
import type { ComicVineConfig, ComicVineTestResult } from '../../../api/types';

/*
 * Data access for Settings -> General (FRG-UI-020 / FRG-API-018).
 *
 * The ComicVine credential resource is a typed singleton like the naming /
 * media-management config (FRG-API-013's pattern): a GET reports configured
 * status + source, never the key value; a PUT persists a non-blank key (a
 * blank PUT keeps the stored value server-side — the UI never special-cases
 * this, it is a property of the endpoint) and the server's own response is
 * written back into the cache so every reader (this screen, and later any
 * other credential-status consumer) sees the fresh status without a refetch.
 * The connectivity test exercises the EFFECTIVE key server-side (env or file,
 * whichever is active) — the request carries no body, since the test is a
 * property of the currently-active configuration, not of the unsaved form.
 */

export function useComicVineConfig(): UseQueryResult<ComicVineConfig> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.config.general(),
    queryFn: () => fetcher<ComicVineConfig>('/api/v1/config/general'),
  });
}

/**
 * PUT body for Settings -> General (FRG-API-018 / FRG-UI-031). Both fields are
 * independent and OPTIONAL: omit `comicvine_api_key` (or send blank) to keep
 * the stored key; omit `comicvine_ignored_publishers` to keep the stored list
 * (a string — including '' — sets it). A save touching one field leaves the
 * other alone server-side.
 */
export interface PutGeneralConfigBody {
  comicvine_api_key?: string;
  comicvine_ignored_publishers?: string;
}

export function usePutComicVineConfig(): UseMutationResult<
  ComicVineConfig,
  Error,
  PutGeneralConfigBody
> {
  const fetcher = useFetcher();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: PutGeneralConfigBody) =>
      fetcher<ComicVineConfig>('/api/v1/config/general', {
        method: 'PUT',
        body,
      }),
    // Replacing the cache entry with the server's own response IS the
    // invalidation: the next read (this screen, or a future AddSeries retry
    // that re-checks status) sees the new configured/source without a
    // separate refetch round-trip.
    onSuccess: (saved) => client.setQueryData(queryKeys.config.general(), saved),
  });
}

export function useTestComicVine(): UseMutationResult<
  ComicVineTestResult,
  Error,
  void
> {
  const fetcher = useFetcher();
  return useMutation({
    mutationFn: () =>
      fetcher<ComicVineTestResult>('/api/v1/config/comicvine/test', {
        method: 'POST',
      }),
  });
}
