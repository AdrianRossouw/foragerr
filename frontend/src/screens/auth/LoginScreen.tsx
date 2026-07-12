import { useId, useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useLogin } from '../../api/authHooks';
import { ApiRequestError } from '../../api/fetcher';
import { useAuthStore } from '../../store/authStore';
import { LogoMarkIcon } from '../../components/icons';
import { safeReturnPath } from '../../auth/returnPath';
import styles from './LoginScreen.module.css';

/**
 * Login screen (m8-auth-core, tasks 4.1/5.6). Username, password, a
 * "remember this device" checkbox, and a submit — minimal and
 * tokens-compliant (M9 polishes visuals). The backend's failure contract is
 * deliberately generic (401 on ANY bad credential), so the form never
 * distinguishes "wrong username" from "wrong password" either
 * (FRG-AUTH-002/010: no user-enumeration surface).
 *
 * No focus trap: this is a full route, not a modal — the browser's normal tab
 * order applies. `return` is read from the query string AuthGate/the fetcher's
 * 401 interception populate, and revalidated here too (defense in depth
 * against a hand-crafted /login?return= link).
 */
export function LoginScreen() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const login = useLogin();
  const setAuthenticated = useAuthStore((s) => s.setAuthenticated);

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const usernameId = useId();
  const passwordId = useId();
  const rememberId = useId();

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    login.mutate(
      { username, password, remember },
      {
        onSuccess: (res) => {
          setAuthenticated(res.username);
          navigate(safeReturnPath(searchParams.get('return')), { replace: true });
        },
        onError: (err) => {
          // The backend never distinguishes bad-user from bad-password (any
          // failure is a 401 with the same generic body) — the form doesn't
          // either. A 429 means failed-attempt throttling has kicked in
          // (FRG-AUTH-009): the operator must WAIT, not retry — telling them to
          // "try again" would contradict the documented backoff. A non-401/429
          // failure (network/5xx) gets its own message so an operator isn't
          // told their password is wrong when the backend is simply unreachable.
          if (err instanceof ApiRequestError && err.status === 401) {
            setError('Invalid username or password.');
          } else if (err instanceof ApiRequestError && err.status === 429) {
            setError(
              'Too many failed attempts. Please wait a moment before trying again.',
            );
          } else {
            setError('Could not sign in. Try again.');
          }
        },
      },
    );
  };

  const submitting = login.isPending;

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.brand} aria-hidden>
          <LogoMarkIcon size={24} />
          <span className={styles.brandWord}>
            Forage<span className={styles.brandWordAccent}>rr</span>
          </span>
        </div>
        <form className={styles.form} onSubmit={onSubmit} noValidate>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={usernameId}>
              Username
            </label>
            <input
              id={usernameId}
              className={styles.input}
              type="text"
              name="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              disabled={submitting}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={passwordId}>
              Password
            </label>
            <input
              id={passwordId}
              className={styles.input}
              type="password"
              name="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={submitting}
            />
          </div>
          <div className={styles.rememberRow}>
            <input
              id={rememberId}
              className={styles.checkbox}
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              disabled={submitting}
            />
            <label className={styles.rememberLabel} htmlFor={rememberId}>
              Remember this device
            </label>
          </div>
          {error && (
            <div className={styles.error} role="alert">
              {error}
            </div>
          )}
          <button type="submit" className={styles.submit} disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
}
