import { useMutation, useQuery, type UseMutationResult, type UseQueryResult } from '@tanstack/react-query';
import { queryKeys } from './queryKeys';
import { useFetcher } from './fetcher';

/*
 * Auth data-access hooks (m8-auth-core FRG-AUTH-002/004; lifecycle endpoints
 * added by m8-keys-opds FRG-AUTH-004/005/006/007). Thin wrappers over the
 * fixed backend contract:
 *   GET  /api/v1/auth/me     -> 200 {username} authenticated, 401 otherwise
 *   POST /api/v1/auth/login -> 200 {username} + sets the session cookie,
 *                               401 {"message":"invalid credentials"} on ANY
 *                               failure (bad user, bad password — never
 *                               distinguished, so the UI never can either)
 *   POST /api/v1/auth/logout -> 204, invalidates the session server-side
 *
 * None of these three paths are 401-intercepted by the fetcher (see
 * fetcher.tsx's AUTH_EXEMPT_PATHS): each has its own caller-owned handling —
 * `AuthGate` for `me`, `LoginScreen` for `login` (a 401 here is an expected,
 * inline-rendered "wrong credentials" outcome, not a session-loss signal).
 *
 * Settings -> Security (m8-keys-opds, design.md "Decision 2"):
 *   GET  /api/v1/auth/credentials       -> 200 {username, ...} non-secret status
 *   POST /api/v1/auth/password          -> {current_password, new_password}
 *   POST /api/v1/auth/opds-password     -> {current_password (ADMIN), new_password}
 *   POST /api/v1/auth/api-key/rotate    -> {current_password} -> {api_key} ONCE
 *   POST /api/v1/auth/logout-all        -> 204, no body
 * Every credential WRITE re-auths with the current admin password and fails
 * with a generic 403 on a bad one (uniform re-auth rule — never distinguished
 * from a bad new-password, same "no enumeration" posture as login). None of
 * these need to sit in fetcher.tsx's AUTH_EXEMPT_PATHS: their failure mode is
 * 403 (re-auth refusal, caller-rendered inline), not 401 — a 401 here would
 * mean the session itself died, which the interceptor should still catch.
 * logout-all is the one exception with no re-auth failure mode at all (it
 * grants nothing — pure session destruction, design.md "friction is the
 * enemy" for the shared-device recovery path); its caller flips the auth
 * store directly on success, mirroring `LogoutButton` (see Security.tsx).
 */

export interface AuthMeResponse {
  username: string;
}

/**
 * Non-secret Settings -> Security status (FRG-AUTH-004/005/007). The backend
 * contract fixes `username`; the other fields are documented in design.md
 * ("key rotated-at, OPDS-differs-from-admin flag") but optional here so the
 * page degrades gracefully (omits the extra copy) if the backend ships them
 * under different names or later than this change's frontend half.
 */
export interface AuthCredentialsResponse {
  username: string;
  api_key_rotated_at?: string | null;
  opds_password_set?: boolean;
}

export interface ChangePasswordPayload {
  current_password: string;
  new_password: string;
}

export interface ChangeOpdsPasswordPayload {
  /** The ADMIN password, not an existing OPDS one (design.md Decision 2). */
  current_password: string;
  new_password: string;
}

export interface RotateApiKeyPayload {
  current_password: string;
}

/** The raw key, present in this ONE response and never again (FRG-AUTH-007). */
export interface RotateApiKeyResponse {
  api_key: string;
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

/** Settings -> Security page header + card status (username, etc.). */
export function useAuthCredentials(): UseQueryResult<AuthCredentialsResponse> {
  const fetcher = useFetcher();
  return useQuery({
    queryKey: queryKeys.auth.credentials(),
    queryFn: () => fetcher<AuthCredentialsResponse>('/api/v1/auth/credentials'),
  });
}

/** Web-password change (FRG-AUTH-004 tail): acting session survives. */
export function useChangePassword(): UseMutationResult<
  void,
  unknown,
  ChangePasswordPayload
> {
  const fetcher = useFetcher();
  return useMutation({
    // gcTime: 0 so the submitted current password does not linger in the
    // MutationCache (state.variables) after the observer unmounts — a secret in
    // memory outliving its use (gate finding). Cards also .reset() on success.
    gcTime: 0,
    mutationFn: (payload) =>
      fetcher<void>('/api/v1/auth/password', { method: 'POST', body: payload }),
  });
}

/** OPDS-password change (FRG-AUTH-005 flip): admin-authorized, independent field. */
export function useChangeOpdsPassword(): UseMutationResult<
  void,
  unknown,
  ChangeOpdsPasswordPayload
> {
  const fetcher = useFetcher();
  return useMutation({
    // gcTime: 0 — see useChangePassword; keeps the admin password out of the
    // MutationCache after unmount.
    gcTime: 0,
    mutationFn: (payload) =>
      fetcher<void>('/api/v1/auth/opds-password', {
        method: 'POST',
        body: payload,
      }),
  });
}

/** API-key rotation (FRG-AUTH-007): the raw key is returned exactly once. */
export function useRotateApiKey(): UseMutationResult<
  RotateApiKeyResponse,
  unknown,
  RotateApiKeyPayload
> {
  const fetcher = useFetcher();
  return useMutation({
    // gcTime: 0 is critical here: without it the MutationCache retains BOTH the
    // submitted admin password (state.variables) AND the raw rotated key
    // (state.data) for the default 5 min after the modal closes — defeating the
    // display-once guarantee (FRG-AUTH-007). The card also calls .reset() the
    // moment it lifts the key into local display state.
    gcTime: 0,
    mutationFn: (payload) =>
      fetcher<RotateApiKeyResponse>('/api/v1/auth/api-key/rotate', {
        method: 'POST',
        body: payload,
      }),
  });
}

/** Logout-all (FRG-AUTH-004 tail): deletes every session row, acting one included. */
export function useLogoutAll(): UseMutationResult<void, unknown, void> {
  const fetcher = useFetcher();
  return useMutation({
    mutationFn: () =>
      fetcher<void>('/api/v1/auth/logout-all', { method: 'POST' }),
  });
}
