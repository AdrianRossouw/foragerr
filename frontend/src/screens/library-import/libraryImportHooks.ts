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
import type { CommandResource, LibraryImportGroup } from '../../api/types';

/*
 * Data access for the library-import screen (FRG-UI-015 / FRG-IMP-023),
 * following the manual-import hooks' shape (source-keyed query, command-
 * dispatch mutations watched via useCommandStatus).
 *
 * Surface (design decision 6):
 *   POST  /api/v1/library-import/scan        {rootFolderId}  -> CommandResource
 *   GET   /api/v1/library-import?rootFolderId=&page=          paged groups
 *   PATCH /api/v1/library-import/groups/{id} {state}|{cvVolumeId}
 *   POST  /api/v1/library-import/execute     {groupIds, addOptions} -> CommandResource
 *
 * Staging is persisted server-side (survives restarts). The list refetches on
 * every mount (a command can finish while the screen is unmounted) and on the
 * explicit invalidations after scan/PATCH/execute — never behind the user's
 * back while the screen stays open.
 */

/**
 * One group exactly as GET /api/v1/library-import serializes it: the camelCase
 * `LibraryImportGroup` contract verbatim (no spelling tolerance — the wire
 * shape is pinned). Only `confidence` gets touched: contractually 0..1, it is
 * clamped so display math (`Math.round(c * 100)%`) can never overflow.
 */
export function toLibraryImportGroup(raw: LibraryImportGroup): LibraryImportGroup {
  return { ...raw, confidence: Math.min(1, Math.max(0, raw.confidence)) };
}

/** The query key mirroring GET /api/v1/library-import?rootFolderId=. */
export function libraryImportKey(rootFolderId: number) {
  return queryKeys.libraryImport.forRoot(rootFolderId);
}

/**
 * Staged groups for one root folder (FRG-UI-015), walking the paged envelope
 * like `useSeriesIndex` (a big library stages more than one page). While the
 * screen stays mounted the list only recomputes on the explicit invalidations
 * after scan/PATCH/execute (staleTime Infinity — no focus refetch clobbers a
 * review session), but EVERY mount refetches: a scan/execute command that
 * finished while the screen was unmounted must show its results on return
 * (staging is small and local, and the cached rows render while the refetch
 * runs, so there is no flicker).
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
      const rows = await fetchAllPages<LibraryImportGroup>(
        fetcher,
        (page) =>
          `/api/v1/library-import?rootFolderId=${rootFolderId}&page=${page}&pageSize=${MAX_PAGE_SIZE}`,
      );
      return rows.map(toLibraryImportGroup);
    },
    enabled: rootFolderId !== null,
    staleTime: Infinity,
    refetchOnMount: 'always',
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

/**
 * The PATCH body: a state change XOR a ComicVine match override (combining
 * `cvVolumeId` with a state is a backend 400). `state: 'proposed'` puts a
 * group back into review; a `cvVolumeId` override sets BOTH the proposed and
 * confirmed ids server-side, so the display fields always match what imports.
 */
export type LibraryImportGroupPatch =
  | { state: 'confirmed' | 'skipped' | 'proposed' }
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
