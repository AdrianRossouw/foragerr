import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { queryKeys } from '../../../api/queryKeys';
import { useFetcher } from '../../../api/fetcher';
import type {
  CommandResource,
  MediaManagementConfig,
  NamingConfig,
  NamingTokens,
  RenamePreviewEntry,
} from '../../../api/types';

/*
 * Data access for the naming / media-management settings page (FRG-UI-012).
 *
 * The two config resources are typed singletons (FRG-API-013): a GET seeds the
 * form, a PUT validates + persists and writes the server's own response back
 * into the cache. The token vocabulary (GET /config/naming/tokens) is static
 * for a build, so it never refetches. The rename preview (GET /rename) is a
 * pure server-side computation; execution is the explicit POST /rename that
 * enqueues the rename-series command, watched via the shared command machinery.
 */

export function useNamingConfig(): UseQueryResult<NamingConfig> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.config.naming(),
    queryFn: () => fetcher<NamingConfig>('/api/v1/config/naming'),
  });
}

export function useMediaManagementConfig(): UseQueryResult<MediaManagementConfig> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.config.mediaManagement(),
    queryFn: () => fetcher<MediaManagementConfig>('/api/v1/config/mediamanagement'),
  });
}

export function useNamingTokens(): UseQueryResult<NamingTokens> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.config.namingTokens(),
    queryFn: () => fetcher<NamingTokens>('/api/v1/config/naming/tokens'),
    // The token vocabulary is a property of the build's renderer, not of the
    // stored config — never refetch it behind the user's back.
    staleTime: Infinity,
  });
}

export function usePutNamingConfig(): UseMutationResult<NamingConfig, Error, NamingConfig> {
  const fetcher = useFetcher();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: NamingConfig) =>
      fetcher<NamingConfig>('/api/v1/config/naming', { method: 'PUT', body }),
    onSuccess: (saved) => client.setQueryData(queryKeys.config.naming(), saved),
  });
}

export function usePutMediaManagementConfig(): UseMutationResult<
  MediaManagementConfig,
  Error,
  MediaManagementConfig
> {
  const fetcher = useFetcher();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: MediaManagementConfig) =>
      fetcher<MediaManagementConfig>('/api/v1/config/mediamanagement', {
        method: 'PUT',
        body,
      }),
    onSuccess: (saved) =>
      client.setQueryData(queryKeys.config.mediaManagement(), saved),
  });
}

/**
 * The rename preview for one series (FRG-PP-012). Only fires for a real series
 * id; the result lists ONLY files that would change and touches no disk. Never
 * refetched behind the user's back — it is recomputed on explicit re-open.
 */
export function useRenamePreview(
  seriesId: number | null,
): UseQueryResult<RenamePreviewEntry[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.rename.forSeries(seriesId ?? -1),
    queryFn: () =>
      fetcher<RenamePreviewEntry[]>(`/api/v1/rename?seriesId=${seriesId}`),
    enabled: seriesId !== null,
    staleTime: Infinity,
    retry: false,
  });
}

/** POST /api/v1/rename — enqueue the rename-series command for a series. */
export function useExecuteRename(): UseMutationResult<CommandResource, Error, number> {
  const fetcher = useFetcher();
  return useMutation({
    mutationFn: (seriesId: number) =>
      fetcher<CommandResource>('/api/v1/rename', {
        method: 'POST',
        body: { seriesId },
      }),
  });
}
