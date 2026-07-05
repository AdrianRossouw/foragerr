import { describe, it, expect } from 'vitest';
import type { ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { createQueryClient } from '../queryClient';
import { FetcherProvider, type Fetcher } from './fetcher';
import { useSeriesList, useSeriesDetail, useQueuePage, useReleases } from './hooks';
import { fakeFetcher } from '../test/fakeFetcher';
import {
  mockSeriesList,
  mockSeriesDetail,
  mockQueuePage1,
  mockReleases,
} from '../test/mockData';

/**
 * FRG-UI-001 — Scenario: Query keys mirror API resource paths.
 * Each data-access hook must register under the mirroring key and issue exactly
 * one request to the corresponding URL path. Driven by a FAKE fetcher (no backend).
 */
function makeWrapper(client: QueryClient, fetcher: Fetcher) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <FetcherProvider fetcher={fetcher}>{children}</FetcherProvider>
    </QueryClientProvider>
  );
}

function cachedKeys(client: QueryClient): unknown[][] {
  return client.getQueryCache().getAll().map((q) => q.queryKey as unknown[]);
}

describe('FRG-UI-001: query keys mirror API resource paths', () => {
  it("FRG-UI-001 — ['series'] backs one GET /api/v1/series", async () => {
    const client = createQueryClient();
    const { spy, fetcher } = fakeFetcher(() => mockSeriesList);
    const { result } = renderHook(() => useSeriesList(), {
      wrapper: makeWrapper(client, fetcher),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith('/api/v1/series');
    expect(cachedKeys(client)).toContainEqual(['series']);
  });

  it("FRG-UI-001 — ['series', id] backs one GET /api/v1/series/:id", async () => {
    const client = createQueryClient();
    const { spy, fetcher } = fakeFetcher(() => mockSeriesDetail);
    const { result } = renderHook(() => useSeriesDetail(7), {
      wrapper: makeWrapper(client, fetcher),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith('/api/v1/series/7');
    expect(cachedKeys(client)).toContainEqual(['series', 7]);
  });

  it("FRG-UI-001 — ['queue', page] backs one GET /api/v1/queue?page=", async () => {
    const client = createQueryClient();
    const { spy, fetcher } = fakeFetcher(() => mockQueuePage1);
    const { result } = renderHook(() => useQueuePage(2), {
      wrapper: makeWrapper(client, fetcher),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith('/api/v1/queue?page=2');
    expect(cachedKeys(client)).toContainEqual(['queue', 2]);
  });

  it("FRG-UI-001 — ['release', issueId] backs one GET /api/v1/release?issueId=", async () => {
    const client = createQueryClient();
    const { spy, fetcher } = fakeFetcher(() => mockReleases);
    const { result } = renderHook(() => useReleases(42), {
      wrapper: makeWrapper(client, fetcher),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith('/api/v1/release?issueId=42');
    expect(cachedKeys(client)).toContainEqual(['release', 42]);
  });
});
