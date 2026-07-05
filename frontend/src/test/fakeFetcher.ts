import { vi, type Mock } from 'vitest';
import type { Fetcher } from '../api/fetcher';

/**
 * A fake fetcher for tests: a Vitest spy (for call assertions) plus a value cast to
 * the generic `Fetcher` type (for injection). No live backend is contacted.
 */
export function fakeFetcher(
  resolver: (path: string, init?: RequestInit) => unknown,
): {
  spy: Mock<(path: string, init?: RequestInit) => Promise<unknown>>;
  fetcher: Fetcher;
} {
  const spy = vi.fn(
    async (path: string, init?: RequestInit): Promise<unknown> =>
      resolver(path, init),
  );
  return { spy, fetcher: spy as unknown as Fetcher };
}
