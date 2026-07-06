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
  ApiPage,
  CommandResource,
  MediaManagementConfig,
  NamingConfig,
  NamingTokens,
  RenamePreviewEntry,
} from '../../../api/types';

/** Command lifecycle statuses that mean a rename is still running. */
const LIVE_COMMAND_STATUSES = new Set(['queued', 'started']);

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

/**
 * The in-flight ``rename-series`` command for one series, if any (FRG-UI-012).
 *
 * The rename preview panel is transient (unmounts on close), so its own
 * ``commandId`` state is lost on close+reopen — reopening while a previously
 * confirmed rename is still running would otherwise re-arm Confirm and allow a
 * duplicate rename-series for the same series. This consults the server's
 * command list for an active (queued/started) ``rename-series`` whose payload
 * targets ``seriesId`` (the backend enqueues ``{ series_id }``), so the panel
 * can stay disabled across a reopen. Polls while one is live and stops once it
 * is not, mirroring ``useCommandStatus``.
 */
export function useActiveRenameSeriesCommand(
  seriesId: number | null,
): UseQueryResult<CommandResource | null> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: [...queryKeys.command.all(), 'active-rename', seriesId ?? -1],
    queryFn: async () => {
      const page = await fetcher<ApiPage<CommandResource>>(
        '/api/v1/command?page=1&pageSize=200&sortKey=queued_at&sortDirection=desc',
      );
      const active = page.records.find(
        (c) =>
          c.name === 'rename-series' &&
          LIVE_COMMAND_STATUSES.has(c.status) &&
          c.payload?.series_id === seriesId,
      );
      return active ?? null;
    },
    enabled: seriesId !== null,
    // Poll while a rename is live so the panel un-disables promptly on finish.
    refetchInterval: (query) => (query.state.data ? 2000 : false),
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
