import { createContext, useContext, type ReactNode } from 'react';

/*
 * Injected fetcher (FRG-UI-001).
 *
 * A Fetcher takes an API path (plus optional method/body for mutations) and
 * resolves the parsed JSON body. The default implementation wraps
 * window.fetch; tests inject a FAKE fetcher (a spy returning typed mock data)
 * so no live backend is ever contacted. Every data-access hook reads its
 * fetcher from context, so there is a single seam for both production wiring
 * and test doubles.
 */
export interface FetcherOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  /** JSON-serialized as the request body when present. */
  body?: unknown;
}

export type Fetcher = <T>(path: string, options?: FetcherOptions) => Promise<T>;

export const defaultFetcher: Fetcher = async <T,>(
  path: string,
  options?: FetcherOptions,
): Promise<T> => {
  const hasBody = options?.body !== undefined;
  const res = await fetch(path, {
    method: options?.method ?? 'GET',
    headers: {
      Accept: 'application/json',
      ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(hasBody ? { body: JSON.stringify(options?.body) } : {}),
  });
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${path}`);
  }
  // 204 No Content (e.g. DELETE /series/{id}) has no JSON body.
  if (res.status === 204) {
    return undefined as T;
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
