import { createContext, useContext, type ReactNode } from 'react';
import { useAuthStore } from '../store/authStore';

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
  /**
   * Cancellation signal (FRG-UI-005: the Add Series autosuggest wires
   * React Query's per-query AbortSignal through here so an in-flight
   * suggest request for a superseded term is aborted rather than left to
   * resolve into a stale, unrenderable response).
   */
  signal?: AbortSignal;
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

/**
 * Auth endpoints own their OWN 401 handling and are exempt from the generic
 * interception below (m8-auth-core, FRG-AUTH-002/010):
 *   - `login` — a 401 here is an expected, inline "wrong credentials" outcome
 *     the login form renders itself; treating it as a session-loss signal
 *     would redirect the login screen to... the login screen.
 *   - `me` — the boot-time check `AuthGate` runs is EXPECTED to 401 for an
 *     anonymous visitor; `AuthGate` already turns that into the unauthenticated
 *     state + redirect itself, with the return path it needs.
 *   - `logout` — always exempt for symmetry; the contract never documents a
 *     401 here, and a logout call is never itself a signal of session loss.
 */
const AUTH_EXEMPT_PATHS: ReadonlySet<string> = new Set([
  '/api/v1/auth/login',
  '/api/v1/auth/logout',
  '/api/v1/auth/me',
]);

export const defaultFetcher: Fetcher = async <T,>(
  path: string,
  init?: FetcherInit,
): Promise<T> => {
  const hasBody = init?.body !== undefined;
  const res = await fetch(path, {
    method: init?.method ?? 'GET',
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(hasBody ? { body: JSON.stringify(init?.body) } : {}),
    ...(init?.signal ? { signal: init.signal } : {}),
  });
  if (!res.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = (await res.json()) as ApiErrorBody;
    } catch {
      body = null;
    }
    // Central 401 interception (FRG-AUTH-010): any OTHER endpoint 401ing means
    // the session died (expired, logged out elsewhere, revoked) mid-use.
    // Flip the auth store — `AuthGate` observes the transition and redirects
    // to /login, preserving wherever the user currently is as the return path.
    // Read via `getState()`, not the hook: this module has no component tree.
    if (res.status === 401 && !AUTH_EXEMPT_PATHS.has(path)) {
      useAuthStore.getState().setUnauthenticated();
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
