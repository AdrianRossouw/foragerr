import { useEffect, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuthMe } from '../api/authHooks';
import { useAuthStore } from '../store/authStore';
import { FullPageLoading } from '../components/FullPageLoading';
import { safeReturnPath } from './returnPath';

const LOGIN_PATH = '/login';

/**
 * Auth gate (m8-auth-core, FRG-AUTH-002/010): the single place the SPA decides
 * whether protected content or the login screen is reachable. Wraps the whole
 * routed app (mounted between `BrowserRouter` and `App` in main.tsx) rather
 * than guarding routes individually — one seam, matching the backend's own
 * "one dependency above every router" default-deny posture.
 *
 * Boot sequence: GET /api/v1/auth/me runs once; while it is pending every
 * route (including /login) renders the shared full-page loading state, so an
 * already-authenticated visitor never sees the login form flash, and a
 * protected screen never flashes for an anonymous one. Once it resolves:
 *   - success -> auth store flips to `authenticated`; if the visitor is
 *     sitting on /login (e.g. a stale bookmark, or reloaded mid-login) they
 *     are sent to the `return` query param or home instead of the form.
 *   - 401 -> auth store flips to `unauthenticated`; if the visitor is NOT
 *     already on /login they are redirected there with `?return=` set to
 *     wherever they were, so login lands them back where they meant to go.
 *
 * The SAME store also receives writes from `defaultFetcher`'s central 401
 * interception (any other endpoint 401ing mid-session) and from `LoginScreen`
 * / the logout control on success — this component reacts uniformly to all of
 * them, it does not care which one flipped the status.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const me = useAuthMe();
  const status = useAuthStore((s) => s.status);
  const setAuthenticated = useAuthStore((s) => s.setAuthenticated);
  const setUnauthenticated = useAuthStore((s) => s.setUnauthenticated);

  // Push the boot-time query's outcome into the auth store exactly once per
  // settled result — the store (not this query) is what the fetcher's 401
  // interception and the rest of the app read.
  useEffect(() => {
    if (me.isSuccess) setAuthenticated(me.data.username);
    else if (me.isError) setUnauthenticated();
  }, [me.isSuccess, me.isError, me.data, setAuthenticated, setUnauthenticated]);

  const onLoginRoute = location.pathname === LOGIN_PATH;

  useEffect(() => {
    if (status === 'unauthenticated' && !onLoginRoute) {
      const target = `${location.pathname}${location.search}`;
      navigate(`${LOGIN_PATH}?return=${encodeURIComponent(target)}`, {
        replace: true,
      });
      return;
    }
    if (status === 'authenticated' && onLoginRoute) {
      const params = new URLSearchParams(location.search);
      // safeReturnPath resolves the attacker-controllable `return` against the
      // real origin and falls back to `/` for anything cross-origin or
      // malformed — a substring check would let `/\evil.com` through and crash
      // navigate() on a cross-origin history mutation.
      navigate(safeReturnPath(params.get('return')), { replace: true });
    }
  }, [status, onLoginRoute, location, navigate]);

  if (status === 'checking') return <FullPageLoading />;
  // A redirect is pending in the effect above for both of these combinations —
  // render the loading state rather than the (wrong) content for one tick.
  if (status === 'unauthenticated' && !onLoginRoute) return <FullPageLoading />;
  if (status === 'authenticated' && onLoginRoute) return <FullPageLoading />;

  return <>{children}</>;
}
