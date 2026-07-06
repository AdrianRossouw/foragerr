import {
  useMutation,
  useQuery,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { queryKeys } from '../../api/queryKeys';
import { useFetcher } from '../../api/fetcher';
import type {
  CommandResource,
  ManualImportEntry,
  ManualImportFileSpec,
} from '../../api/types';

/*
 * Data access for the manual-import overlay (FRG-UI-014 / FRG-API-015).
 *
 * The list endpoint is a pure computation over the shared import pipeline: for a
 * managed folder (`path`) OR a blocked download (`downloadId`) it returns every
 * candidate file's would-be verdict, verbatim rejection reasons, suggested
 * mapping, and embedded-ComicInfo summary — touching no disk beyond inspection.
 * The two source keys are mutually exclusive (the backend 400s if both/neither
 * are given), so the overlay always carries exactly one.
 *
 * Execution is the explicit POST that enqueues the exclusivity-guarded
 * `manual-import` command on the pp-pool, watched through the shared command
 * machinery (`useCommandStatus`). The command runs the FULL decision set over
 * each corrected mapping, so there is no "force" that skips validation.
 */

/** The single source a manual-import overlay lists candidates for. */
export type ManualImportSource =
  | { kind: 'path'; path: string }
  | { kind: 'download'; downloadId: string };

/**
 * The POST /manual-import request. `files` carries the operator-corrected
 * mappings; `downloadId` is present ONLY when the overlay was opened for a
 * blocked download, so the backend re-evaluates with download scope. A
 * path-picker overlay omits it entirely.
 */
export interface ExecuteManualImportInput {
  files: ManualImportFileSpec[];
  downloadId?: string;
}

/** The query key mirroring a source's `?path=` XOR `?downloadId=` URL. */
export function manualImportKey(source: ManualImportSource) {
  return source.kind === 'path'
    ? queryKeys.manualImport.forPath(source.path)
    : queryKeys.manualImport.forDownload(source.downloadId);
}

/**
 * Candidate files for one source (FRG-UI-014). Never refetched behind the
 * user's back — it is recomputed only on an explicit invalidate (after a
 * completed manual-import command), so in-flight overrides survive polling.
 */
export function useManualImportCandidates(
  source: ManualImportSource | null,
): UseQueryResult<ManualImportEntry[]> {
  const fetcher = useFetcher();
  return useQuery({
    // A disabled query still needs a stable key; the null placeholder never runs.
    queryKey: source ? manualImportKey(source) : queryKeys.manualImport.forPath(''),
    queryFn: () => {
      const url =
        source!.kind === 'path'
          ? `/api/v1/manual-import?path=${encodeURIComponent(source!.path)}`
          : `/api/v1/manual-import?downloadId=${encodeURIComponent(source!.downloadId)}`;
      return fetcher<ManualImportEntry[]>(url);
    },
    enabled: source !== null,
    staleTime: Infinity,
    retry: false,
  });
}

/**
 * POST /api/v1/manual-import — enqueue the `manual-import` command with the
 * operator-corrected mappings. Returns the CommandResource so the overlay can
 * watch it via `useCommandStatus` and reflect the outcome on completion.
 */
export function useExecuteManualImport(): UseMutationResult<
  CommandResource,
  Error,
  ExecuteManualImportInput
> {
  const fetcher = useFetcher();
  return useMutation({
    mutationFn: ({ files, downloadId }: ExecuteManualImportInput) =>
      fetcher<CommandResource>('/api/v1/manual-import', {
        method: 'POST',
        // Only send downloadId when opened for a blocked download; the
        // path-picker entry point posts just the corrected files.
        body: downloadId === undefined ? { files } : { downloadId, files },
      }),
  });
}
