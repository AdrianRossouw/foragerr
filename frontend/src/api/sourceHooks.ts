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
 * entitlements, and an open detail re-derive together (the whole inventory is
 * one review surface). The session cookie is NEVER read
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

export interface UpdateSourceInput {
  sourceId: number;
  /** Flip the auto-sync control (FRG-SRC-004). */
  auto_sync?: boolean;
  /**
   * WHOLE-LIST replace of the source's publisher rules (FRG-SRC-012) — the
   * editor sends the list it wants and `[]` clears them. Takes effect on the
   * next sync, and only over rows the automatic classifier still owns.
   */
  publisher_rules?: string[];
}

/**
 * PATCH /api/v1/sources/{id} — change a source's mutable controls post-connect
 * (FRG-SRC-004 / FRG-SRC-012). `auto_sync`: flipping it ON persists the flag
 * only and NEVER retroactively accepts existing entitlements (the backend
 * auto-accepts confident matches on a subsequent sync). `publisher_rules`: a
 * whole-list replace inside the source's existing encrypted settings envelope —
 * a source with no loadable settings (disconnected) answers 409 rather than
 * minting an envelope. Only the fields supplied are sent, so a caller never
 * silently rewrites the control it did not touch. On success we sweep the whole
 * sources family so the toggle, the rules editor and any dependent view
 * re-derive together.
 */
export function useUpdateSource(): UseMutationResult<
  StoreSourceResource,
  Error,
  UpdateSourceInput
> {
  const fetcher = useFetcher();
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: ({ sourceId, auto_sync, publisher_rules }) =>
      fetcher<StoreSourceResource>(`/api/v1/sources/${sourceId}`, {
        method: 'PATCH',
        body: {
          ...(auto_sync !== undefined ? { auto_sync } : {}),
          ...(publisher_rules !== undefined ? { publisher_rules } : {}),
        },
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

export interface RecomputeProposalsInput {
  sourceId: number;
  /**
   * Also refresh the source's no-plausible-match markers (FRG-SRC-013). OFF by
   * default — re-asking ComicVine about every "we looked, there is nothing" row
   * is real budget spend, so it happens only on an explicit request.
   */
  includeMarkers?: boolean;
}

/**
 * POST /api/v1/sources/{id}/recompute-proposals — enqueue the resumable bulk
 * refresh of one source's stale stored proposals (FRG-SRC-013), answering 202
 * with the queued command.
 *
 * The work happens in the background through the batch lane: it walks rows in
 * least-recently-attempted order, stops cleanly at the ComicVine budget wall
 * having refreshed a prefix, and resumes from the same ordering when re-run —
 * so triggering it is cheap and safely repeatable (the command dedup collapses
 * an impatient double-click onto one run). Only rows still in review move;
 * matched and ignored decisions are never recomputed.
 *
 * A source with no ComicVine key configured rejects with a 409
 * `ApiRequestError` whose message the caller surfaces verbatim. On success we
 * sweep the sources family: nothing has changed YET (the command is only
 * queued), but the source's own command/sync state is part of that family and
 * the sweep is what keeps the enqueue from being the one action that leaves the
 * screen reading stale.
 */
export function useRecomputeProposals(): UseMutationResult<
  SourceSyncResponse,
  Error,
  RecomputeProposalsInput
> {
  const fetcher = useFetcher();
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: ({ sourceId, includeMarkers }) =>
      fetcher<SourceSyncResponse>(
        `/api/v1/sources/${sourceId}/recompute-proposals`,
        {
          method: 'POST',
          // The default request body stays empty: `include_markers` defaults to
          // false server-side, and only an explicit opt-in states it.
          body: includeMarkers ? { include_markers: true } : {},
        },
      ),
    onSuccess: invalidate,
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

export interface AddEntitlementInput {
  entitlementId: number;
  /**
   * An explicit ComicVine volume to add instead of the row's own stored
   * proposal (FRG-UI-039): what the per-row search picker sends when the
   * operator chooses a candidate the automatic proposal never found. Omitted
   * (the proposal-accept path) the backend uses the stored proposal. The
   * endpoint degrades an already-in-library volume to a plain match
   * (FRG-SRC-008), so this is safe even when the pick turns out to be owned.
   */
  cvVolumeId?: number;
}

/** POST /sources/entitlements/{id}/add — add a new series, then link it. */
export function useAddEntitlement(): UseMutationResult<
  EntitlementResource,
  Error,
  AddEntitlementInput
> {
  const fetcher = useFetcher();
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: ({ entitlementId, cvVolumeId }) =>
      fetcher<EntitlementResource>(
        `/api/v1/sources/entitlements/${entitlementId}/add`,
        {
          method: 'POST',
          // The historical proposal-accept request body stays byte-identical
          // ({}); only an explicit pick carries cv_volume_id.
          body: cvVolumeId != null ? { cv_volume_id: cvVolumeId } : {},
        },
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

/**
 * POST /sources/entitlements/{id}/retry-download — re-queue a FAILED download
 * (FRG-SRC-009). Failed-only on the server: a row in any other download state
 * rejects with a 409 `ApiRequestError` and nothing changes. Success clears the
 * recorded failure and re-queues the grab, so the usual sources-family
 * invalidation re-renders the row out of its failed state.
 */
export function useRetryDownload(): UseMutationResult<
  EntitlementResource,
  Error,
  number
> {
  const fetcher = useFetcher();
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: (entitlementId) =>
      fetcher<EntitlementResource>(
        `/api/v1/sources/entitlements/${entitlementId}/retry-download`,
        { method: 'POST' },
      ),
    onSuccess: invalidate,
  });
}

export interface BulkEntitlementResult {
  applied: number;
  skipped: number;
  /**
   * PER-ROW failures, keyed by entitlement id (the backend's `dict[int, str]`,
   * so the JSON keys are id strings). A bulk call is a 200 even with entries
   * here: one un-acceptable row never vetoes the batch, it just reports itself.
   */
  errors: Record<string, string>;
}

/**
 * The bulk request shapes (FRG-SRC-011 / FRG-UI-043). `ignore` / `restore` /
 * `accept` are id-only; `apply_to_group` (the group-header search/match,
 * FRG-UI-043) carries EXACTLY ONE resolved target for the whole id list — a
 * `seriesId` for a candidate already in the library (match every member) or a
 * `cvVolumeId` for a candidate not yet added (the server adds it once and
 * leaves the rest as swept proposals). The two `apply_to_group` variants are a
 * discriminated union so a caller cannot send both targets or neither.
 */
export type BulkEntitlementInput =
  | { action: 'ignore' | 'restore' | 'accept'; entitlementIds: number[] }
  | { action: 'apply_to_group'; entitlementIds: number[]; seriesId: number }
  | { action: 'apply_to_group'; entitlementIds: number[]; cvVolumeId: number };

/**
 * POST /sources/entitlements/bulk — one review action over several rows.
 * `ignore` / `restore` / `accept` are id-only; `accept` (FRG-SRC-011) applies
 * EACH row's OWN stored proposal server-side in a per-row transaction, which is
 * what makes "apply to a whole group/bundle" one request instead of the old
 * client-side loop. `apply_to_group` (FRG-UI-043) instead applies ONE shared
 * target — a library series id, or a ComicVine volume id the server adds once —
 * across every id in the group, which is what makes resolving a whole same-title
 * run one action rather than one pick per row. (Per-row `match` stays row-scoped:
 * a single series id cannot be right across heterogeneous rows, but a group is
 * homogeneous by construction, which is exactly what makes it safe here.)
 */
export function useBulkEntitlements(): UseMutationResult<
  BulkEntitlementResult,
  Error,
  BulkEntitlementInput
> {
  const fetcher = useFetcher();
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: (input) => {
      const body: Record<string, unknown> = {
        action: input.action,
        entitlement_ids: input.entitlementIds,
      };
      // Exactly one target for apply_to_group; the id-only actions send neither.
      if (input.action === 'apply_to_group') {
        if ('seriesId' in input) body.series_id = input.seriesId;
        else body.cv_volume_id = input.cvVolumeId;
      }
      return fetcher<BulkEntitlementResult>('/api/v1/sources/entitlements/bulk', {
        method: 'POST',
        body,
      });
    },
    onSuccess: invalidate,
  });
}
