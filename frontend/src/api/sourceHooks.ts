import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { queryKeys } from './queryKeys';
import { useFetcher } from './fetcher';
import type {
  EntitlementDetailResource,
  EntitlementResource,
  SourceConnectResponse,
  SourceSyncResponse,
  StoreSourceResource,
} from './types';

/*
 * Store-source data-access hooks (FRG-UI-029). Reads over the sources CRUD +
 * entitlement review surface (backend/src/foragerr/api/sources.py); every
 * mutation invalidates the bare ['sources'] family so the list, each source's
 * entitlements, an open detail, and the sidebar new-count re-derive together
 * (the whole inventory is one review surface). The session cookie is NEVER read
 * back from the server (write-only, FRG-SRC-002) — connect/reconnect carry it
 * one-way in the request body only.
 */

/** GET /api/v1/sources — configured sources with their PUBLIC settings. */
export function useSources(): UseQueryResult<StoreSourceResource[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.sources.list(),
    queryFn: () => fetcher<StoreSourceResource[]>('/api/v1/sources'),
  });
}

/** True when any configured source's session has expired (badge/banner/health). */
export function useHasExpiredSource(): boolean {
  const { data } = useSources();
  return (data ?? []).some((s) => s.connection_state === 'expired');
}

/**
 * All of one source's entitlements (FRG-SRC-004). The whole list is fetched
 * once and the manage view filters client-side (segments + non-comic toggle),
 * so the segment counts stay live off a single cache entry. `enabled` gates the
 * fetch until a connected source id is known.
 */
export function useEntitlements(
  sourceId: number | null,
): UseQueryResult<EntitlementResource[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.sources.entitlements(sourceId ?? -1),
    queryFn: () =>
      fetcher<EntitlementResource[]>(`/api/v1/sources/${sourceId}/entitlements`),
    enabled: sourceId != null,
  });
}

/**
 * One entitlement plus its collected-edition fill-sets (FRG-SRC-007) for the
 * expandable reconcile detail. `enabled` keeps it dormant until the row is
 * expanded so the list never pays for detail it is not showing.
 */
export function useEntitlementDetail(
  entitlementId: number | null,
  enabled: boolean,
): UseQueryResult<EntitlementDetailResource> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.sources.entitlementDetail(entitlementId ?? -1),
    queryFn: () =>
      fetcher<EntitlementDetailResource>(
        `/api/v1/sources/entitlements/${entitlementId}`,
      ),
    enabled: enabled && entitlementId != null,
  });
}

/**
 * The unreviewed-`new` count across connected sources for the Sources nav badge
 * (FRG-UI-029). Fetches the server-filtered `?review_status=new` slice per
 * connected source (the small set, not the whole inventory) and sums; dormant
 * with no connected source, so an unconfigured install pays nothing.
 */
export function useSourcesNewCount(
  sourceIds: number[],
): UseQueryResult<number> {
  const fetcher = useFetcher();
  const idsHash = [...sourceIds].sort((a, b) => a - b).join(',');
  return useQuery({
    queryKey: queryKeys.sources.newCount(idsHash),
    queryFn: async () => {
      let total = 0;
      for (const id of sourceIds) {
        const rows = await fetcher<EntitlementResource[]>(
          `/api/v1/sources/${id}/entitlements?review_status=new`,
        );
        total += rows.length;
      }
      return total;
    },
    enabled: sourceIds.length > 0,
  });
}

/** Shared invalidation: sweep the whole sources family (list + entitlements). */
function useInvalidateSources(): () => void {
  const queryClient = useQueryClient();
  return () =>
    void queryClient.invalidateQueries({ queryKey: queryKeys.sources.all() });
}

export interface ConnectSourceInput {
  type: string;
  name?: string;
  session_cookie: string;
  auto_sync: boolean;
}

/**
 * POST /api/v1/sources — connect a source (FRG-SRC-002). The backend runs a
 * LIVE order-list validation BEFORE persisting; a failure rejects with an
 * `ApiRequestError` naming the cause and persists nothing.
 */
export function useConnectSource(): UseMutationResult<
  SourceConnectResponse,
  Error,
  ConnectSourceInput
> {
  const fetcher = useFetcher();
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: (v) =>
      fetcher<SourceConnectResponse>('/api/v1/sources', {
        method: 'POST',
        body: {
          type: v.type,
          name: v.name,
          settings: { session_cookie: v.session_cookie },
          auto_sync: v.auto_sync,
        },
      }),
    onSuccess: invalidate,
  });
}

/** POST /api/v1/sources/{id}/reconnect — re-paste a cookie on an expired source. */
export function useReconnectSource(): UseMutationResult<
  SourceConnectResponse,
  Error,
  { sourceId: number; session_cookie: string }
> {
  const fetcher = useFetcher();
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: ({ sourceId, session_cookie }) =>
      fetcher<SourceConnectResponse>(`/api/v1/sources/${sourceId}/reconnect`, {
        method: 'POST',
        body: { settings: { session_cookie } },
      }),
    onSuccess: invalidate,
  });
}

/** POST /api/v1/sources/{id}/disconnect — delete the credential, keep data. */
export function useDisconnectSource(): UseMutationResult<
  StoreSourceResource,
  Error,
  number
> {
  const fetcher = useFetcher();
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: (sourceId) =>
      fetcher<StoreSourceResource>(`/api/v1/sources/${sourceId}/disconnect`, {
        method: 'POST',
      }),
    onSuccess: invalidate,
  });
}

/**
 * POST /api/v1/sources/{id}/sync — enqueue a manual "Sync now" (202). Returns
 * the enqueued command so the caller can watch it to terminal and re-invalidate
 * the entitlements when it completes.
 */
export function useSyncSource(): UseMutationResult<
  SourceSyncResponse,
  Error,
  number
> {
  const fetcher = useFetcher();
  return useMutation({
    mutationFn: (sourceId) =>
      fetcher<SourceSyncResponse>(`/api/v1/sources/${sourceId}/sync`, {
        method: 'POST',
      }),
  });
}

/** POST /sources/entitlements/{id}/match — link to a series and accept. */
export function useMatchEntitlement(): UseMutationResult<
  EntitlementResource,
  Error,
  { entitlementId: number; seriesId: number }
> {
  const fetcher = useFetcher();
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: ({ entitlementId, seriesId }) =>
      fetcher<EntitlementResource>(
        `/api/v1/sources/entitlements/${entitlementId}/match`,
        { method: 'POST', body: { series_id: seriesId } },
      ),
    onSuccess: invalidate,
  });
}

/** POST /sources/entitlements/{id}/add — add a new series, then link it. */
export function useAddEntitlement(): UseMutationResult<
  EntitlementResource,
  Error,
  number
> {
  const fetcher = useFetcher();
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: (entitlementId) =>
      fetcher<EntitlementResource>(
        `/api/v1/sources/entitlements/${entitlementId}/add`,
        { method: 'POST', body: {} },
      ),
    onSuccess: invalidate,
  });
}

/** POST /sources/entitlements/{id}/ignore — exclude from pending review. */
export function useIgnoreEntitlement(): UseMutationResult<
  EntitlementResource,
  Error,
  number
> {
  const fetcher = useFetcher();
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: (entitlementId) =>
      fetcher<EntitlementResource>(
        `/api/v1/sources/entitlements/${entitlementId}/ignore`,
        { method: 'POST' },
      ),
    onSuccess: invalidate,
  });
}

/** POST /sources/entitlements/{id}/restore — return an ignored row to `new`. */
export function useRestoreEntitlement(): UseMutationResult<
  EntitlementResource,
  Error,
  number
> {
  const fetcher = useFetcher();
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: (entitlementId) =>
      fetcher<EntitlementResource>(
        `/api/v1/sources/entitlements/${entitlementId}/restore`,
        { method: 'POST' },
      ),
    onSuccess: invalidate,
  });
}

export interface BulkEntitlementResult {
  applied: number;
  skipped: number;
  errors: string[];
}

/**
 * POST /sources/entitlements/bulk — one review action over several rows. Only
 * `ignore` and `restore` are id-only (the `match` action needs one shared
 * series_id, which cannot be right across heterogeneous rows — per-row Match /
 * Add stays row-scoped). Backs the bulk-select accept/ignore workflow at scale.
 */
export function useBulkEntitlements(): UseMutationResult<
  BulkEntitlementResult,
  Error,
  { action: 'ignore' | 'restore'; entitlementIds: number[] }
> {
  const fetcher = useFetcher();
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: ({ action, entitlementIds }) =>
      fetcher<BulkEntitlementResult>('/api/v1/sources/entitlements/bulk', {
        method: 'POST',
        body: { action, entitlement_ids: entitlementIds },
      }),
    onSuccess: invalidate,
  });
}
