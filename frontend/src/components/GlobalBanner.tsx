import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSources } from '../api/sourceHooks';
import styles from './GlobalBanner.module.css';

/**
 * Global store-session banner (FRG-UI-029): a full-width amber strip above the
 * header that appears whenever any configured source's session has expired, so
 * the operator sees it from ANY screen. A Reconnect action deep-links to
 * Sources; a dismiss hides it for the session (it re-raises if a fresh expiry
 * lands). Reads the authoritative `connection_state` off the shared sources
 * cache — reconnecting flips the state and clears the banner with no reload.
 */
export function GlobalBanner() {
  const navigate = useNavigate();
  const { data } = useSources();
  const expired = (data ?? []).filter((s) => s.connection_state === 'expired');
  const isExpired = expired.length > 0;
  const [dismissed, setDismissed] = useState(false);

  // Re-arm the banner when expiry clears, so a later re-expiry shows again.
  useEffect(() => {
    if (!isExpired) setDismissed(false);
  }, [isExpired]);

  if (!isExpired || dismissed) return null;

  const name = expired[0].name;
  return (
    <div className={styles.banner} role="alert" data-testid="global-store-banner">
      <span className={styles.icon} aria-hidden>
        <i className="fa-solid fa-triangle-exclamation" />
      </span>
      <span className={styles.message}>
        <strong>{name} session expired.</strong> Foragerr can&rsquo;t sync new
        purchases until you reconnect.
      </span>
      <button
        type="button"
        className={styles.reconnect}
        onClick={() => navigate('/sources')}
      >
        Reconnect
      </button>
      <button
        type="button"
        className={styles.dismiss}
        aria-label="Dismiss"
        onClick={() => setDismissed(true)}
      >
        <i className="fa-solid fa-xmark" aria-hidden />
      </button>
    </div>
  );
}
