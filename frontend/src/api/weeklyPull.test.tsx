import { describe, it, expect } from 'vitest';
import type { ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { createQueryClient } from '../queryClient';
import { FetcherProvider, type Fetcher } from './fetcher';
import { useWeeklyPull } from './hooks';
import { fakeFetcher } from '../test/fakeFetcher';
import { pageOf } from '../test/mockData';
import type { PullEntryRecord } from './types';

/**
 * FRG-UI-018 / FRG-API-019 — useWeeklyPull aggregates the WHOLE ISO week: it
 * walks every page of the pull endpoint (pageSize 200) and returns one flat
 * record list. This pins the multi-page walk and the cross-page dedup by stable
 * row id (a projection shifting between page fetches must not yield two rows —
 * and two React keys — for the same stored entry).
 */

function makeRow(id: number, over: Partial<PullEntryRecord> = {}): PullEntryRecord {
  return {
    id,
    week: '2026-W27',
    publisher: 'Image',
    seriesName: `Series ${id}`,
    issueNumber: '1',
    releaseDate: '2026-07-01',
    cvSeriesId: null,
    cvIssueId: null,
    matchType: 'id',
    matchedIssueId: id,
    state: 'missing_wanted',
    series: { id, title: `Series ${id}` },
    issue: { id, issueNumber: '1', title: null },
    ...over,
  };
}

function makeWrapper(client: QueryClient, fetcher: Fetcher) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <FetcherProvider fetcher={fetcher}>{children}</FetcherProvider>
    </QueryClientProvider>
  );
}

const pagePath = (week: string, page: number) =>
  `/api/v1/pull?week=${week}&page=${page}&pageSize=200&sortKey=release_date&sortDirection=asc`;

describe('FRG-UI-018: useWeeklyPull page aggregation', () => {
  it('FRG-UI-018 — fetches both pages, concatenates them, and dedups an overlapping row by id', async () => {
    // 201 records across two pages (pageSize 200). Page 2 re-serves row 200 —
    // an overlap a mid-aggregation projection shift could produce — alongside
    // the genuinely-new row 201. The result must be 201 unique rows (no dup key
    // for id 200), proving both pages were fetched and deduped.
    const page1 = Array.from({ length: 200 }, (_, i) => makeRow(i + 1)); // ids 1..200
    const page2 = [makeRow(200), makeRow(201)]; // id 200 overlaps page 1

    const { spy, fetcher } = fakeFetcher((path) => {
      const page = Number(new URL(`http://x${path}`).searchParams.get('page'));
      const records = page === 1 ? page1 : page2;
      return pageOf(records, { page, pageSize: 200, totalRecords: 201 });
    });
    const client = createQueryClient();

    const { result } = renderHook(() => useWeeklyPull('2026-W27'), {
      wrapper: makeWrapper(client, fetcher),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // Both pages were requested.
    expect(spy).toHaveBeenCalledWith(pagePath('2026-W27', 1));
    expect(spy).toHaveBeenCalledWith(pagePath('2026-W27', 2));

    const rows = result.current.data ?? [];
    // 201 unique rows — the overlapping id-200 row was collapsed, not duplicated.
    expect(rows).toHaveLength(201);
    const ids = rows.map((r) => r.id);
    expect(new Set(ids).size).toBe(201);
    expect(ids.filter((id) => id === 200)).toHaveLength(1);
  });
});
