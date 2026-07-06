import { describe, it, expect } from 'vitest';
import type { ReactNode } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { createQueryClient } from '../queryClient';
import { FetcherProvider, type Fetcher } from './fetcher';
import { useSuggest, SUGGEST_DEBOUNCE_MS } from './hooks';
import { fakeFetcher } from '../test/fakeFetcher';

/**
 * FRG-UI-005 — the suggest API hook + fetcher wiring backing the Add Series
 * autosuggest dropdown (design decision #5 / tasks.md B.1): a >=3-char gate,
 * a ~250ms debounce (not one request per keystroke), and term-keyed caching
 * so a stale in-flight response for a superseded term never overwrites a
 * newer one. Real timers throughout — the debounce is exercised by actually
 * waiting it out, avoiding fake-timer/microtask ordering pitfalls.
 */

function makeWrapper(client: QueryClient, fetcher: Fetcher) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <FetcherProvider fetcher={fetcher}>{children}</FetcherProvider>
    </QueryClientProvider>
  );
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function afterDebounce() {
  return wait(SUGGEST_DEBOUNCE_MS + 100);
}

describe('FRG-UI-005: useSuggest', () => {
  it('FRG-UI-005 — no request is issued for a term under 3 characters, even past the debounce interval', async () => {
    const client = createQueryClient();
    const { spy, fetcher } = fakeFetcher(() => ({ records: [], complete: true }));
    const { rerender } = renderHook(({ term }) => useSuggest(term), {
      wrapper: makeWrapper(client, fetcher),
      initialProps: { term: '' },
    });

    rerender({ term: 'sa' });
    await act(() => afterDebounce());

    expect(spy).not.toHaveBeenCalled();
  });

  it('FRG-UI-005 — the request is debounced: rapid keystrokes collapse into one request for the final term', async () => {
    const client = createQueryClient();
    const { spy, fetcher } = fakeFetcher(() => ({ records: [], complete: true }));
    const { rerender } = renderHook(({ term }) => useSuggest(term), {
      wrapper: makeWrapper(client, fetcher),
      initialProps: { term: '' },
    });

    // A burst of keystrokes well inside the debounce window...
    rerender({ term: 's' });
    await act(() => wait(60));
    rerender({ term: 'sa' });
    await act(() => wait(60));
    rerender({ term: 'sag' });
    await act(() => wait(60));
    rerender({ term: 'saga' });

    // ...must settle to exactly ONE request, for the final term only, and
    // it must carry an AbortSignal (cancellation is wired through the
    // fetcher, not merely decorative).
    await act(() => afterDebounce());
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith(
      '/api/v1/series/lookup/suggest?term=saga',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("FRG-UI-005 — a stale in-flight response for a superseded term never overwrites the newer term's data", async () => {
    const client = createQueryClient();
    let resolveStale!: (value: unknown) => void;
    const staleResponse = new Promise((resolve) => {
      resolveStale = resolve;
    });

    const { fetcher } = fakeFetcher((path) => {
      if (path === '/api/v1/series/lookup/suggest?term=sag') return staleResponse;
      if (path === '/api/v1/series/lookup/suggest?term=saga') {
        return {
          records: [
            {
              cv_volume_id: 1,
              name: 'Saga',
              publisher: null,
              start_year: null,
              image_url: null,
              count_of_issues: null,
              have_it: false,
            },
          ],
          complete: true,
        };
      }
      throw new Error(`unexpected request: ${path}`);
    });

    const { result, rerender } = renderHook(({ term }) => useSuggest(term), {
      wrapper: makeWrapper(client, fetcher),
      initialProps: { term: '' },
    });

    // 'sag' fires and is left in flight (never resolved yet)...
    rerender({ term: 'sag' });
    await act(() => afterDebounce());

    // ...then the user keeps typing to 'saga', which fires its own request
    // and resolves before the stale one.
    rerender({ term: 'saga' });
    await act(() => afterDebounce());
    await waitFor(() => expect(result.current.data?.records[0]?.name).toBe('Saga'));

    // NOW the stale 'sag' response finally arrives. It must not clobber the
    // current ('saga') data — this hook instance is subscribed to the
    // 'saga'-keyed query, not the abandoned 'sag' one.
    await act(async () => {
      resolveStale({
        records: [
          {
            cv_volume_id: 2,
            name: 'WRONG STALE RESULT',
            publisher: null,
            start_year: null,
            image_url: null,
            count_of_issues: null,
            have_it: false,
          },
        ],
        complete: true,
      });
      await Promise.resolve();
    });

    expect(result.current.data?.records[0]?.name).toBe('Saga');
  });
});
