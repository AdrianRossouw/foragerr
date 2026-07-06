import { createContext, useContext, type ReactNode } from 'react';

/*
 * Injected fetcher (FRG-UI-001).
 *
 * A Fetcher takes an API path (plus an optional method/body init for mutations)
 * and resolves the parsed JSON body. The default implementation wraps
 * window.fetch; tests inject a FAKE fetcher (a spy returning typed mock data) so
 * no live backend is ever contacted. Every data-access hook reads its fetcher
 * from context, so there is a single seam for both production wiring and test
 * doubles.
 */

/** Optional init for mutating requests; omitted entirely for plain GETs. */
export interface FetcherInit {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  /** JSON-serialized as the request body when present. */
  body?: unknown;
}

/** The backend's uniform 4xx error shape (FRG-API-002). */
export interface ApiErrorBody {
  message: string;
  errors: { field: string | null; message: string }[];
}

/**
 * A non-2xx response, carrying the parsed uniform error body when the backend
 * supplied one. `message` is the backend's message verbatim, so deterministic
 * errors — e.g. the expired-release-cache "search again" message (FRG-UI-007) —
 * surface to the user unaltered, and screens can render `body.errors[]` against
 * specific form fields (FRG-UI-008).
 */
export class ApiRequestError extends Error {
  readonly status: number;
  readonly body: ApiErrorBody | null;

  constructor(status: number, body: ApiErrorBody | null, path: string) {
    super(body?.message ?? `Request failed: ${status} ${path}`);
    this.name = 'ApiRequestError';
    this.status = status;
    this.body = body;
  }
}

/**
 * Structural ComicVine credential-failure discriminator (FRG-UI-005): the
 * backend marks an auth failure by naming `comicvine_api_key` in the uniform
 * error body's `errors[]` (the same field channel settings screens consume),
 * so screens classify on the field — never by sniffing message prose.
 */
export function isComicVineAuthError(error: unknown): boolean {
  return (
    error instanceof ApiRequestError &&
    (error.body?.errors ?? []).some(
      (entry) => entry.field === 'comicvine_api_key',
    )
  );
}

export type Fetcher = <T>(path: string, init?: FetcherInit) => Promise<T>;

export const defaultFetcher: Fetcher = async <T,>(
  path: string,
  init?: FetcherInit,
): Promise<T> => {
  const hasBody = init?.body !== undefined;
  const res = await fetch(path, {
    method: init?.method ?? 'GET',
    headers: {
      Accept: 'application/json',
      ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(hasBody ? { body: JSON.stringify(init?.body) } : {}),
  });
  if (!res.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = (await res.json()) as ApiErrorBody;
    } catch {
      body = null;
    }
    throw new ApiRequestError(res.status, body, path);
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
