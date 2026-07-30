import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { queryKeys } from '../../api/queryKeys';
import { useFetcher } from '../../api/fetcher';
import type { FieldValues, ImplementationSchema } from '../schemaForm/schemaTypes';
import type {
  ProviderKindConfig,
  ProviderResource,
  ProviderTestResult,
} from './providerTypes';

/*
 * Data access for provider settings (FRG-UI-008/009), generic over the kind.
 *
 * REST contract (Sonarr-shaped, mirrored by the backend provider routers):
 *   GET    {apiBase}          -> ProviderResource[]        key [kind]
 *   GET    {apiBase}/schema   -> ImplementationSchema[]    key [kind, 'schema']
 *   POST   {apiBase}          -> create (body incl. implementation, settings)
 *   PUT    {apiBase}/{id}     -> partial update; omitted secret settings keys
 *                                mean "keep the stored value" (write-only)
 *   DELETE {apiBase}/{id}     -> remove
 *   POST   {apiBase}/test     -> connectivity test (never persists, so it never
 *                                invalidates); a body carrying the kind's row
 *                                id merges over that row's stored settings,
 *                                the same write-only rule PUT follows
 */

export function useProviders(
  kind: ProviderKindConfig,
): UseQueryResult<ProviderResource[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.provider.all(kind.key),
    queryFn: () => fetcher<ProviderResource[]>(kind.apiBase),
  });
}

export function useProviderSchemas(
  kind: ProviderKindConfig,
): UseQueryResult<ImplementationSchema[]> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.provider.schema(kind.key),
    queryFn: () => fetcher<ImplementationSchema[]>(`${kind.apiBase}/schema`),
  });
}

export interface SaveProviderVars {
  id?: number;
  body: Record<string, unknown>;
}

export function useSaveProvider(
  kind: ProviderKindConfig,
): UseMutationResult<ProviderResource, Error, SaveProviderVars> {
  const fetcher = useFetcher();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: SaveProviderVars) =>
      id === undefined
        ? fetcher<ProviderResource>(kind.apiBase, { method: 'POST', body })
        : fetcher<ProviderResource>(`${kind.apiBase}/${id}`, {
            method: 'PUT',
            body,
          }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: queryKeys.provider.all(kind.key) }),
  });
}

export function useDeleteProvider(
  kind: ProviderKindConfig,
): UseMutationResult<void, Error, number> {
  const fetcher = useFetcher();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      fetcher<void>(`${kind.apiBase}/${id}`, { method: 'DELETE' }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: queryKeys.provider.all(kind.key) }),
  });
}

export interface TestProviderVars {
  implementation: string;
  settings: FieldValues;
  /**
   * The saved row under test, named by the kind's `testIdField`. Present only
   * when editing: it tells the backend to merge the submitted settings over
   * the stored ones, which is the only way the write-only secret reaches the
   * live probe. An add form has no row to merge with and omits both.
   */
  client_id?: number;
  indexer_id?: number;
}

export function useTestProvider(
  kind: ProviderKindConfig,
): UseMutationResult<ProviderTestResult, Error, TestProviderVars> {
  const fetcher = useFetcher();
  return useMutation({
    mutationFn: (body: TestProviderVars) =>
      fetcher<ProviderTestResult>(`${kind.apiBase}/test`, {
        method: 'POST',
        body,
      }),
  });
}
