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
export type Fetcher = <T>(path: string, init?: RequestInit) => Promise<T>;

/**
 * A non-2xx API response. `message` carries the backend's uniform 4xx body
 * message verbatim (`{"message": ..., "errors": [...]}`, FRG-API-002) so
 * deterministic errors — e.g. the expired-release-cache "search again" message
 * (FRG-UI-007) — can be surfaced to the user unaltered.
 */
export class ApiRequestError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiRequestError';
    this.status = status;
  }
}

export const defaultFetcher: Fetcher = async <T,>(
  path: string,
  init?: RequestInit,
): Promise<T> => {
  const res = await fetch(path, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body != null ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    let message = `Request failed: ${res.status} ${path}`;
    try {
      const body: unknown = await res.json();
      if (
        typeof body === 'object' &&
        body !== null &&
        typeof (body as { message?: unknown }).message === 'string'
      ) {
        message = (body as { message: string }).message;
      }
    } catch {
      // Non-JSON error body — keep the generic message.
    }
    throw new ApiRequestError(res.status, message);
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
