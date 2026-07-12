import styles from './FullPageLoading.module.css';

/**
 * Full-page loading state (m8-auth-core): shown by `AuthGate` while the
 * boot-time GET /api/v1/auth/me is pending, and briefly while an
 * authenticated/unauthenticated transition is about to redirect — never any
 * protected screen content or the login form flashes underneath it.
 */
export function FullPageLoading() {
  return (
    <div className={styles.wrap} role="status" aria-live="polite">
      Loading…
    </div>
  );
}
