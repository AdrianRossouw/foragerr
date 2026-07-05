import { createContext, useContext, type ReactNode } from 'react';

/*
 * Injected fetcher (FRG-UI-001).
 *
 * A Fetcher takes an API path and resolves the parsed JSON body. The default
 * implementation wraps window.fetch; tests inject a FAKE fetcher (a spy returning
 * typed mock data) so no live backend is ever contacted in this scaffold pass.
 * Every data-access hook reads its fetcher from context, so there is a single
 * seam for both production wiring and test doubles.
 */
export type Fetcher = <T>(path: string) => Promise<T>;

export const defaultFetcher: Fetcher = async <T,>(path: string): Promise<T> => {
  const res = await fetch(path, { headers: { Accept: 'application/json' } });
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${path}`);
  }
  return (await res.json()) as T;
};

const FetcherContext = createContext<Fetcher>(defaultFetcher);

export function FetcherProvider({
  fetcher,
  children,
}: {
  fetcher: Fetcher;
  children: ReactNode;
}) {
  return (
    <FetcherContext.Provider value={fetcher}>{children}</FetcherContext.Provider>
  );
}

export function useFetcher(): Fetcher {
  return useContext(FetcherContext);
}
