import { describe, it, expect, vi } from 'vitest';
import type { ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { createQueryClient } from '../queryClient';
import { FetcherProvider, type Fetcher } from './fetcher';
import { queryKeys } from './queryKeys';
import { useAddSeries, useDeleteSeries } from './hooks';
import { fakeFetcher } from '../test/fakeFetcher';
import { mockSeriesCreated } from '../test/mockData';

/**
 * FRG-UI-021 — the grouped projection (['series','groups']) is a SIBLING of the
 * flat index key (['series']) that add/delete invalidate with exact:true, so it
 * must be invalidated explicitly on those paths or the franchise view goes
 * stale after a series is added or removed.
 */

function makeWrapper(client: QueryClient, fetcher: Fetcher) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <FetcherProvider fetcher={fetcher}>{children}</FetcherProvider>
    </QueryClientProvider>
  );
}

describe('FRG-UI-021: add/delete invalidate the grouped projection', () => {
  it('FRG-UI-021 — useAddSeries invalidates ["series","groups"]', async () => {
    const client = createQueryClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { fetcher } = fakeFetcher(() => mockSeriesCreated);
    const { result } = renderHook(() => useAddSeries(), {
      wrapper: makeWrapper(client, fetcher),
    });

    result.current.mutate({
      cv_volume_id: 1,
      root_folder_id: 1,
      format_profile_id: 1,
      monitor_strategy: 'all',
      monitor_new_items: 'all',
      search_on_add: false,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.series.groups() });
  });

  it('FRG-UI-021 — useDeleteSeries invalidates ["series","groups"]', async () => {
    const client = createQueryClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { fetcher } = fakeFetcher(() => null);
    const { result } = renderHook(() => useDeleteSeries(), {
      wrapper: makeWrapper(client, fetcher),
    });

    result.current.mutate({ seriesId: 7, deleteFiles: false });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.series.groups() });
  });
});
