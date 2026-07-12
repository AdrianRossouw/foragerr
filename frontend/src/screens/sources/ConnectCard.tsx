import { useState } from 'react';
import { Toggle } from '../../components/Toggle';
import {
  useConnectSource,
  useReconnectSource,
  useSyncSource,
} from '../../api/sourceHooks';
import type { StoreSourceResource } from '../../api/types';
import styles from './sources.module.css';

/** Minimum pasted length before Connect enables (design handoff: >12 chars). */
const MIN_COOKIE_LENGTH = 12;

/**
 * Humble connect / reconnect card (FRG-UI-029). Used for a disconnected store
 * (fresh connect) or an expired one (reconnect, with an amber "session kept"
 * note). The cookie is held in local state only, masked in a password field,
 * sent one-way on submit, and NEVER read back from the server (FRG-SRC-002).
 * Connect runs the backend's live order-list validation; success flips the
 * source to `connected` (the parent swaps in the manage view) and a sync is
 * enqueued so entitlements populate; failure surfaces the honest cause.
 */
export function ConnectCard({ source }: { source: StoreSourceResource | null }) {
  const reconnecting = source?.connection_state === 'expired';
  const [cookie, setCookie] = useState('');
  const [helperOpen, setHelperOpen] = useState(false);
  const [autoSync, setAutoSync] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const connect = useConnectSource();
  const reconnect = useReconnectSource();
  const sync = useSyncSource();
  const pending = connect.isPending || reconnect.isPending;

  const enough = cookie.trim().length > MIN_COOKIE_LENGTH;

  const onSuccess = (sourceId: number) => {
    setCookie('');
    setError(null);
    // Kick a sync so the manage view starts filling with entitlements.
    sync.mutate(sourceId);
  };

  const submit = () => {
    if (!enough || pending) return;
    setError(null);
    if (reconnecting && source) {
      reconnect.mutate(
        { sourceId: source.id, session_cookie: cookie.trim() },
        {
          onSuccess: (res) => onSuccess(res.source.id),
          onError: (err) => setError(err.message),
        },
      );
    } else {
      connect.mutate(
        { type: 'humble', session_cookie: cookie.trim(), auto_sync: autoSync },
        {
          onSuccess: (res) => onSuccess(res.source.id),
          onError: (err) => setError(err.message),
        },
      );
    }
  };

  return (
    <div className={styles.card} data-testid="connect-card">
      <div className={styles.cardHeader}>
        <span className={styles.cardTile} aria-hidden>
          <i className="fa-solid fa-bag-shopping" />
        </span>
        <div>
          <div className={styles.cardTitle}>
            {reconnecting
              ? 'Reconnect your Humble Bundle account'
              : 'Connect your Humble Bundle account'}
          </div>
          <div className={styles.cardSub}>
            {reconnecting
              ? 'Paste a fresh session cookie to resume syncing.'
              : 'Sync purchased comics into your Foragerr library.'}
          </div>
        </div>
      </div>

      {reconnecting && (
        <div className={styles.expiredNote} role="note">
          <i className="fa-solid fa-triangle-exclamation" aria-hidden />
          <span>
            Your previous session expired. Your synced comics are kept — paste a
            fresh cookie to resume.
          </span>
        </div>
      )}

      <div className={styles.fieldLabelRow}>
        <span className={styles.fieldLabel} id="cookie-label">
          Humble session cookie
        </span>
        <button
          type="button"
          className={styles.helperToggle}
          aria-expanded={helperOpen}
          onClick={() => setHelperOpen((v) => !v)}
          data-testid="helper-toggle"
        >
          <i className="fa-solid fa-circle-question" aria-hidden /> How do I get
          this?
        </button>
      </div>

      {helperOpen && (
        <div className={styles.helper} data-testid="cookie-helper">
          <div className={styles.helperStep}>
            <span className={styles.stepNum}>1</span>
            <span>
              Use the Foragerr browser extension
              <span className={styles.comingSoon}>Coming soon</span> — one click
              on humblebundle.com grabs the cookie, no DevTools needed.
            </span>
          </div>
          <div className={styles.helperStep}>
            <span className={styles.stepNum}>2</span>
            <span>
              Or grab it manually: sign in at humblebundle.com, open DevTools →
              Application → Cookies, and copy the value of{' '}
              <code className={styles.code}>_simpleauth_sess</code>.
            </span>
          </div>
          <div className={styles.helperStep}>
            <span className={styles.stepNum}>3</span>
            <span>Paste it below and connect. Stored encrypted, used only to read your library.</span>
          </div>
        </div>
      )}

      <input
        type="password"
        className={styles.pasteField}
        aria-labelledby="cookie-label"
        placeholder="_simpleauth_sess=…"
        autoComplete="off"
        spellCheck={false}
        value={cookie}
        onChange={(e) => setCookie(e.target.value)}
        data-testid="cookie-input"
      />

      {!reconnecting && (
        <div className={styles.autoRow}>
          <Toggle
            checked={autoSync}
            onChange={setAutoSync}
            label="Auto-sync new purchases"
            testId="auto-sync-connect"
          />
          <span>
            Auto-sync new purchases (matches &amp; adds confident matches
            automatically)
          </span>
        </div>
      )}

      <div className={styles.connectRow}>
        <button
          type="button"
          className={styles.primaryBtn}
          disabled={!enough || pending}
          onClick={submit}
          data-testid="connect-button"
        >
          {pending
            ? reconnecting
              ? 'Reconnecting…'
              : 'Connecting…'
            : reconnecting
              ? 'Reconnect'
              : 'Connect'}
        </button>
        <span className={styles.privacyNote}>
          <i className="fa-solid fa-lock" aria-hidden /> Stored encrypted, never
          shown again.
        </span>
      </div>

      {error && (
        <div className={styles.connectError} role="alert" data-testid="connect-error">
          {error}
        </div>
      )}
    </div>
  );
}
