import { useNavigate } from 'react-router-dom';
import { useLogout } from '../api/authHooks';
import { useAuthStore } from '../store/authStore';
import styles from './AppShell.module.css';

/**
 * Logout control (m8-auth-core, task 4.1): a header icon button beside the
 * existing system-level actions (health, system status) — the same surface
 * the app already uses to expose whole-app actions, so logout reads as one
 * more of them rather than a bolted-on extra.
 *
 * Calls POST /api/v1/auth/logout, then — regardless of whether that call
 * succeeded or failed (a network hiccup shouldn't strand an operator who
 * wants OUT) — clears the local auth store and navigates to /login.
 * `AuthGate` reacts to the store flip: once it stops rendering the app tree,
 * `AppShell` (and the `WebSocketBridge` it mounts) unmounts, which closes the
 * socket as a side effect of the bridge's own cleanup — no separate "close
 * the socket on logout" wiring is needed here.
 */
export function LogoutButton() {
  const logout = useLogout();
  const navigate = useNavigate();
  const setUnauthenticated = useAuthStore((s) => s.setUnauthenticated);

  const onLogout = () => {
    logout.mutate(undefined, {
      onSettled: () => {
        setUnauthenticated();
        navigate('/login', { replace: true });
      },
    });
  };

  return (
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
  );
}
