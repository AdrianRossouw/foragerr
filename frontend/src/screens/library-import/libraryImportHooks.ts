import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { queryKeys } from '../../api/queryKeys';
import { useFetcher } from '../../api/fetcher';
import { fetchAllPages, MAX_PAGE_SIZE } from '../../api/hooks';
import type {
  CommandResource,
  LibraryImportGroup,
  LibraryImportGroupState,
} from '../../api/types';

/*
 * Data access for the library-import screen (FRG-UI-015 / FRG-IMP-023),
 * following the manual-import hooks' shape (source-keyed query, command-
 * dispatch mutations watched via useCommandStatus).
 *
 * Surface (design decision 6):
 *   POST  /api/v1/library-import/scan        {rootFolderId}  -> CommandResource
 *   GET   /api/v1/library-import?rootFolderId=&page=          paged groups
 *   PATCH /api/v1/library-import/groups/{id} {action}|{cvVolumeId}
 *   POST  /api/v1/library-import/execute     {groupIds, addOptions} -> CommandResource
 *
 * Staging is persisted server-side (survives restarts), so the list is
 * fetched on mount and recomputed ONLY on explicit invalidation — after a
 * scan/execute command completes or a group PATCH lands — never behind the
 * user's back while a review session is open.
 */

/** One group exactly as the wire carries it — key spelling not yet pinned. */
type LibraryImportGroupRaw = Record<string, unknown>;

/** Read a raw field tolerating camelCase or snake_case spellings. */
function field<T>(
  raw: LibraryImportGroupRaw,
  camel: string,
  snake: string,
  fallback: T,
): T {
  const value = raw[camel] !== undefined ? raw[camel] : raw[snake];
  return value === undefined || value === null ? fallback : (value as T);
}

/**
 * Normalize one wire group into the UI's `LibraryImportGroup`. Tolerant on
 * purpose: the backend lands in parallel and its serializer may follow the
 * snake_case series resources OR the camelCase manual-import resources; either
 * spelling maps onto the same normalized shape (like `toQueueItem` does for
 * the queue's naming seam). `confidence` accepts a 0..1 fraction or a 0..100
 * percentage and always yields 0..1.
 */
export function toLibraryImportGroup(
  raw: LibraryImportGroupRaw,
): LibraryImportGroup {
  const confidence = field<number>(raw, 'confidence', 'confidence', 0);
  return {
    id: field<number>(raw, 'id', 'id', 0),
    matchingKey: field<string>(raw, 'matchingKey', 'matching_key', ''),
    folder: field<string>(raw, 'folder', 'folder', ''),
    files: field<string[]>(raw, 'files', 'files', []),
    confidence: confidence > 1 ? confidence / 100 : confidence,
    proposedCvVolumeId: field<number | null>(
      raw,
      'proposedCvVolumeId',
      'proposed_cv_volume_id',
      null,
    ),
    confirmedCvVolumeId: field<number | null>(
      raw,
      'confirmedCvVolumeId',
      'confirmed_cv_volume_id',
      null,
    ),
    state: field<LibraryImportGroupState>(raw, 'state', 'state', 'proposed'),
    name: field<string | null>(raw, 'name', 'name', null),
    startYear: field<number | null>(raw, 'startYear', 'start_year', null),
    publisher: field<string | null>(raw, 'publisher', 'publisher', null),
    imageUrl: field<string | null>(raw, 'imageUrl', 'image_url', null),
    rejections: field<string[]>(raw, 'rejections', 'blocked_reasons', []),
  };
}

/** The query key mirroring GET /api/v1/library-import?rootFolderId=. */
export function libraryImportKey(rootFolderId: number) {
  return queryKeys.libraryImport.forRoot(rootFolderId);
}

/**
 * Staged groups for one root folder (FRG-UI-015), walking the paged envelope
 * like `useSeriesIndex` (a big library stages more than one page). Never
 * refetched behind the user's back (staleTime Infinity): recomputed only on
 * the explicit invalidations after scan/PATCH/execute, so in-flight selection
 * and correction state survive the review session.
 */
export function useLibraryImportGroups(
  rootFolderId: number | null,
): UseQueryResult<LibraryImportGroup[]> {
  const fetcher = useFetcher();
  return useQuery({
    // A disabled query still needs a stable key; the null placeholder never runs.
    queryKey:
      rootFolderId !== null
        ? libraryImportKey(rootFolderId)
        : queryKeys.libraryImport.all(),
    queryFn: async () => {
      const rows = await fetchAllPages<LibraryImportGroupRaw>(
        fetcher,
        (page) =>
          `/api/v1/library-import?rootFolderId=${rootFolderId}&page=${page}&pageSize=${MAX_PAGE_SIZE}`,
      );
      return rows.map(toLibraryImportGroup);
    },
    enabled: rootFolderId !== null,
    staleTime: Infinity,
    retry: false,
  });
}

/**
 * POST /api/v1/library-import/scan — enqueue the read-only `library-import-scan`
 * command for one root. Returns the CommandResource so the screen watches it
 * via `useCommandStatus` and refetches the staged groups on completion.
 */
export function useStartLibraryScan(): UseMutationResult<
  CommandResource,
  Error,
  { rootFolderId: number }
> {
  const fetcher = useFetcher();
  return useMutation({
    mutationFn: ({ rootFolderId }) =>
      fetcher<CommandResource>('/api/v1/library-import/scan', {
        method: 'POST',
        body: { rootFolderId },
      }),
  });
}

/** The PATCH body: a state action XOR a ComicVine match override. */
export type LibraryImportGroupPatch =
  | { action: 'confirm' | 'skip' }
  | { cvVolumeId: number };

/**
 * PATCH /api/v1/library-import/groups/{id} — confirm/skip a group or override
 * its ComicVine match (the override is CV-validated server-side, like add).
 * On success the root's staged list is invalidated so the updated group state
 * renders from the server's truth rather than an optimistic guess.
 */
export function usePatchLibraryImportGroup(
  rootFolderId: number | null,
): UseMutationResult<
  unknown,
  Error,
  { groupId: number; patch: LibraryImportGroupPatch }
> {
  const fetcher = useFetcher();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ groupId, patch }) =>
      fetcher(`/api/v1/library-import/groups/${groupId}`, {
        method: 'PATCH',
        body: patch,
      }),
    onSuccess: () => {
      if (rootFolderId !== null) {
        void queryClient.invalidateQueries({
          queryKey: libraryImportKey(rootFolderId),
        });
      }
    },
  });
}

/** POST /api/v1/library-import/execute body: groups + batch add options. */
export interface ExecuteLibraryImportInput {
  groupIds: number[];
  addOptions: {
    formatProfileId: number | null;
    monitorStrategy: string;
    searchOnAdd: boolean;
  };
}

/**
 * POST /api/v1/library-import/execute — enqueue the `library-import` command
 * that bulk-adds the selected groups' series and imports their existing files
 * through the shared pipeline. Returns the CommandResource for status watching;
 * the screen invalidates the staged list AND the series index on completion.
 */
export function useExecuteLibraryImport(): UseMutationResult<
  CommandResource,
  Error,
  ExecuteLibraryImportInput
> {
  const fetcher = useFetcher();
  return useMutation({
    mutationFn: (input: ExecuteLibraryImportInput) =>
      fetcher<CommandResource>('/api/v1/library-import/execute', {
        method: 'POST',
        body: input,
      }),
  });
}
