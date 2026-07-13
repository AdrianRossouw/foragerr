import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLogout } from '../api/authHooks';
import { useAuthStore } from '../store/authStore';
import styles from './AppShell.module.css';

/**
 * Logout control (m8-auth-core, task 4.1; failure handling: logout-failure-
 * handling): a header icon button beside the existing system-level actions
 * (health, system status) — the same surface the app already uses to expose
 * whole-app actions, so logout reads as one more of them.
 *
 * Calls POST /api/v1/auth/logout and treats the logout as complete ONLY when
 * the server confirms it (FRG-AUTH-004). On success it clears the local auth
 * store and navigates to /login; `AuthGate` reacts to the store flip, so
 * `AppShell` (and the `WebSocketBridge` it mounts) unmounts and the socket
 * closes as a side effect — no separate "close the socket on logout" wiring.
 *
 * On FAILURE (a 4xx/5xx or a network error) it does NOT clear auth state or
 * navigate: the session may still be live and the HttpOnly cookie cannot be
 * cleared client-side, so presenting a successful logout would strand a live
 * session on a shared browser. It surfaces a retryable error and keeps the
 * operator authenticated; a subsequent successful logout then completes.
 */
export function LogoutButton() {
  const logout = useLogout();
  const navigate = useNavigate();
  const setUnauthenticated = useAuthStore((s) => s.setUnauthenticated);
  const [failed, setFailed] = useState(false);

  const onLogout = () => {
    if (logout.isPending) return; // guard a same-tick double activation
    setFailed(false);
    logout.mutate(undefined, {
      onSuccess: () => {
        setUnauthenticated();
        navigate('/login', { replace: true });
      },
      onError: () => {
        setFailed(true);
      },
    });
  };

  return (
    <>
      {failed && (
        <span role="alert" className={styles.logoutError}>
          Couldn&rsquo;t sign out &mdash; try again
        </span>
      )}
      <button
        type="button"
        className={styles.iconButton}
        aria-label="Log out"
        title="Log out"
        data-testid="header-logout"
        disabled={logout.isPending}
        onClick={onLogout}
      >
        <i className="fa-solid fa-arrow-right-from-bracket" aria-hidden />
      </button>
    </>
  );
}
