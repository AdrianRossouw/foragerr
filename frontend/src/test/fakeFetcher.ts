import { vi, type Mock } from 'vitest';
import type { Fetcher, FetcherInit } from '../api/fetcher';

/**
 * A fake fetcher for tests: a Vitest spy (for call assertions) plus a value cast to
 * the generic `Fetcher` type (for injection). No live backend is contacted.
 *
 * The resolver receives the request init as an optional second argument so
 * mutation tests can assert on method/body or simulate backend 4xx failures by
 * throwing an `ApiRequestError`.
 */
export function fakeFetcher(
  resolver: (path: string, init?: FetcherInit) => unknown,
): {
  spy: Mock<(path: string, init?: FetcherInit) => Promise<unknown>>;
  fetcher: Fetcher;
} {
  const spy = vi.fn(
    async (path: string, init?: FetcherInit): Promise<unknown> =>
      resolver(path, init),
  );
  return { spy, fetcher: spy as unknown as Fetcher };
}
