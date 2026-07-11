import { describe, it, expect } from 'vitest';
import type { ReactNode } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { createQueryClient } from '../queryClient';
import { queryKeys } from './queryKeys';
import { FetcherProvider, type Fetcher, type FetcherInit } from './fetcher';
import { useCreatorsList, useSetCreatorFollow, type CreatorsListResult } from './hooks';
import { fakeFetcher } from '../test/fakeFetcher';
import { creatorPageOf, makeCreator } from '../test/mockData';
import type { CreatorResource } from './types';

/**
 * FRG-UI-027 / FRG-CRTR-004 — the creators read + follow hooks.
 *
 * useCreatorsList walks every page and dedups by stable creator id (a mid-walk
 * projection shift must not yield two cards — and two React keys — for one
 * creator). useSetCreatorFollow is optimistic but SCOPED: a failing toggle
 * rolls back ONLY its own creator, never a whole-family snapshot, so overlapping
 * toggles do not clobber one another. Fake fetcher only; no live backend.
 */

function makeWrapper(client: QueryClient, fetcher: Fetcher) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <FetcherProvider fetcher={fetcher}>{children}</FetcherProvider>
    </QueryClientProvider>
  );
}

const listCreatorPath = (page: number) =>
  `/api/v1/creators?page=${page}&pageSize=200&sortKey=name&sortDirection=asc`;

describe('FRG-UI-027: useCreatorsList page aggregation', () => {
  it('FRG-UI-027 — fetches both pages, concatenates them, and dedups an overlapping creator by id', async () => {
    // 201 creators across two pages (pageSize 200). Page 2 re-serves creator 200
    // — an overlap a mid-aggregation projection shift could produce — alongside
    // the genuinely-new creator 201. The result must be 201 unique rows.
    const page1 = Array.from({ length: 200 }, (_, i) =>
      makeCreator({ id: i + 1, name: `Creator ${i + 1}` }),
    ); // ids 1..200
    const page2 = [
      makeCreator({ id: 200, name: 'Creator 200' }), // overlaps page 1
      makeCreator({ id: 201, name: 'Creator 201' }),
    ];

    const { spy, fetcher } = fakeFetcher((path) => {
      const page = Number(new URL(`http://x${path}`).searchParams.get('page'));
      const records = page === 1 ? page1 : page2;
      return creatorPageOf(records, { page, totalRecords: 201, totalCreators: 201 });
    });
    const client = createQueryClient();

    const { result } = renderHook(() => useCreatorsList(), {
      wrapper: makeWrapper(client, fetcher),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // Both pages were requested.
    expect(spy).toHaveBeenCalledWith(listCreatorPath(1));
    expect(spy).toHaveBeenCalledWith(listCreatorPath(2));

    const rows = result.current.data?.records ?? [];
    // 201 unique rows — the overlapping id-200 creator was collapsed, not duped.
    expect(rows).toHaveLength(201);
    const ids = rows.map((r) => r.id);
    expect(new Set(ids).size).toBe(201);
    expect(ids.filter((id) => id === 200)).toHaveLength(1);
  });
});

/** Read the followed flag of one creator out of a seeded list cache entry. */
function followedOf(
  client: QueryClient,
  key: readonly unknown[],
  creatorId: number,
): boolean | undefined {
  const data = client.getQueryData<CreatorsListResult>(key);
  return data?.records.find((r) => r.id === creatorId)?.followed;
}

describe('FRG-CRTR-004: useSetCreatorFollow optimistic rollback is scoped', () => {
  const listKey = queryKeys.creators.list('sortKey=name&sortDirection=asc');

  function seedList(client: QueryClient, records: CreatorResource[]): void {
    client.setQueryData<CreatorsListResult>(listKey, {
      records,
      totalCreators: records.length,
      followedCreators: records.filter((r) => r.followed).length,
    });
  }

  it('FRG-CRTR-004 — a failing PUT rolls back exactly that creator, leaving other rows and the aggregate intact', async () => {
    const client = createQueryClient();
    seedList(client, [
      makeCreator({ id: 1, name: 'A', followed: false }),
      makeCreator({ id: 2, name: 'B', followed: true }),
    ]);
    // The follow PUT always rejects.
    const { fetcher } = fakeFetcher((_path, init?: FetcherInit) => {
      if ((init?.method ?? 'GET') === 'PUT') throw new Error('backend down');
      throw new Error('unexpected read');
    });

    const { result } = renderHook(() => useSetCreatorFollow(), {
      wrapper: makeWrapper(client, fetcher),
    });

    act(() => {
      result.current.mutate({ creatorId: 1, followed: true });
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    // Creator 1 rolled back to unfollowed; creator 2 untouched; aggregate honest.
    expect(followedOf(client, listKey, 1)).toBe(false);
    expect(followedOf(client, listKey, 2)).toBe(true);
    expect(client.getQueryData<CreatorsListResult>(listKey)?.followedCreators).toBe(1);
  });

  it('FRG-CRTR-004 — overlapping toggles: B succeeds, then A fails, and A\'s rollback leaves B\'s new state intact', async () => {
    const client = createQueryClient();
    seedList(client, [
      makeCreator({ id: 1, name: 'A', followed: false }),
      makeCreator({ id: 2, name: 'B', followed: false }),
    ]);

    // Toggle A (creator 1) stays in flight until we reject it; toggle B
    // (creator 2) resolves immediately. A starts first, B completes while A is
    // pending, then A fails — the exact interleaving a whole-family snapshot
    // rollback would mishandle.
    let rejectA!: (reason: unknown) => void;
    const deferredA = new Promise<CreatorResource>((_resolve, reject) => {
      rejectA = reject;
    });
    const { fetcher } = fakeFetcher((path, init?: FetcherInit) => {
      if ((init?.method ?? 'GET') !== 'PUT') throw new Error('unexpected read');
      const id = Number(path.match(/creators\/(\d+)\/follow/)![1]);
      const followed = (init?.body as { followed: boolean }).followed;
      if (id === 1) return deferredA;
      return makeCreator({ id, name: 'B', followed });
    });

    const { result } = renderHook(() => useSetCreatorFollow(), {
      wrapper: makeWrapper(client, fetcher),
    });

    // A starts and applies its optimistic patch (creator 1 → followed).
    act(() => {
      result.current.mutate({ creatorId: 1, followed: true });
    });
    await waitFor(() => expect(followedOf(client, listKey, 1)).toBe(true));

    // B starts, succeeds, and settles (creator 2 → followed) while A is pending.
    act(() => {
      result.current.mutate({ creatorId: 2, followed: true });
    });
    await waitFor(() => expect(followedOf(client, listKey, 2)).toBe(true));

    // A fails — its rollback must revert ONLY creator 1, not B's applied toggle.
    act(() => {
      rejectA(new Error('backend down'));
    });
    await waitFor(() => expect(followedOf(client, listKey, 1)).toBe(false));

    expect(followedOf(client, listKey, 2)).toBe(true);
    // Aggregate reflects B's one surviving follow (started at 0: +1 A, +1 B, −1 A).
    expect(client.getQueryData<CreatorsListResult>(listKey)?.followedCreators).toBe(1);
  });
});
