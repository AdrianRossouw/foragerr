import { vi, type Mock } from 'vitest';
import type { Fetcher, FetcherOptions } from '../api/fetcher';

/**
 * A fake fetcher for tests: a Vitest spy (for call assertions) plus a value cast to
 * the generic `Fetcher` type (for injection). No live backend is contacted.
 * The resolver receives the request options too, so mutation tests can branch
 * on method/body; plain GET resolvers may ignore the second argument.
 */
export function fakeFetcher(
  resolver: (path: string, options?: FetcherOptions) => unknown,
): {
  spy: Mock<(path: string, options?: FetcherOptions) => Promise<unknown>>;
  fetcher: Fetcher;
} {
  const spy = vi.fn(
    (path: string, options?: FetcherOptions): Promise<unknown> =>
      Promise.resolve(resolver(path, options)),
  );
  return { spy, fetcher: spy as unknown as Fetcher };
}
