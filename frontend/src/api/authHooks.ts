import { useMutation, useQuery, type UseMutationResult, type UseQueryResult } from '@tanstack/react-query';
import { queryKeys } from './queryKeys';
import { useFetcher } from './fetcher';

/*
 * Auth data-access hooks (m8-auth-core, FRG-AUTH-002/004). Thin wrappers over
 * the fixed backend contract:
 *   GET  /api/v1/auth/me     -> 200 {username} authenticated, 401 otherwise
 *   POST /api/v1/auth/login -> 200 {username} + sets the session cookie,
 *                               401 {"detail":"invalid credentials"} on ANY
 *                               failure (bad user, bad password — never
 *                               distinguished, so the UI never can either)
 *   POST /api/v1/auth/logout -> 204, invalidates the session server-side
 *
 * None of these three paths are 401-intercepted by the fetcher (see
 * fetcher.tsx's AUTH_EXEMPT_PATHS): each has its own caller-owned handling —
 * `AuthGate` for `me`, `LoginScreen` for `login` (a 401 here is an expected,
 * inline-rendered "wrong credentials" outcome, not a session-loss signal).
 */

export interface AuthMeResponse {
  username: string;
}

export interface LoginPayload {
  username: string;
  password: string;
  /** "Remember this device" — the backend's long-lived session tier. */
  remember: boolean;
}

/** Boot-time / refresh-time "am I logged in" check, consumed by `AuthGate`. */
export function useAuthMe(): UseQueryResult<AuthMeResponse> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.auth.me(),
    queryFn: () => fetcher<AuthMeResponse>('/api/v1/auth/me'),
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export function useLogin(): UseMutationResult<AuthMeResponse, unknown, LoginPayload> {
  const fetcher = useFetcher();
  return useMutation({
    mutationFn: (payload: LoginPayload) =>
      fetcher<AuthMeResponse>('/api/v1/auth/login', { method: 'POST', body: payload }),
  });
}

export function useLogout(): UseMutationResult<void, unknown, void> {
  const fetcher = useFetcher();
  return useMutation({
    mutationFn: () => fetcher<void>('/api/v1/auth/logout', { method: 'POST' }),
  });
}
