import { create } from 'zustand';

/*
 * Auth state (m8-auth-core, FRG-AUTH-002/010) — LOCAL client state mirroring
 * whether the SPA currently holds an authenticated session, never persisted
 * (a stale "authenticated" flag surviving a browser restart would be worse
 * than useless — the cookie is the actual source of truth on the server).
 *
 * Two things read/write this store:
 *   - `AuthGate` (src/auth/AuthGate.tsx): sets `authenticated`/`unauthenticated`
 *     off the boot-time GET /api/v1/auth/me, and off a successful login/logout.
 *   - `defaultFetcher` (src/api/fetcher.tsx): a NON-react module, so it reads
 *     this store via `useAuthStore.getState()` rather than the hook — any 401
 *     from a non-auth endpoint (session died mid-use) flips the store to
 *     `unauthenticated`, which `AuthGate` observes and redirects on.
 *
 * `status` starts at `checking` (FRG-AUTH-010: never briefly render protected
 * UI before the boot check resolves) and only ever moves to `authenticated`
 * or `unauthenticated` — there is no route back to `checking` short of a full
 * page reload.
 */
export type AuthStatus = 'checking' | 'authenticated' | 'unauthenticated';

interface AuthState {
  status: AuthStatus;
  username: string | null;
  setAuthenticated: (username: string) => void;
  setUnauthenticated: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  status: 'checking',
  username: null,
  setAuthenticated: (username) => set({ status: 'authenticated', username }),
  setUnauthenticated: () => set({ status: 'unauthenticated', username: null }),
}));
