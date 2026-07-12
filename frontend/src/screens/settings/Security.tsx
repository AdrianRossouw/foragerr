import { useId, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Toolbar } from '../../components/Toolbar';
import { Modal } from '../../components/Modal';
import { mapApiError } from '../../components/settings/apiErrors';
import { ApiRequestError } from '../../api/fetcher';
import { useAuthStore } from '../../store/authStore';
import {
  useAuthCredentials,
  useChangePassword,
  useChangeOpdsPassword,
  useRotateApiKey,
  useLogoutAll,
} from '../../api/authHooks';
import styles from './security/Security.module.css';

/*
 * Settings -> Security (m8-keys-opds, FRG-AUTH-004/005/007).
 *
 * Four independent cards, each its own re-auth boundary (design.md
 * "Decision 2" — every credential WRITE carries the current admin password;
 * logout-all is the one exception, since it grants nothing and destroying
 * sessions is the shared-device recovery path friction must not gate):
 *   - web password change (acting session survives — no redirect)
 *   - OPDS password change (admin-authorized, independent of the web password)
 *   - API key rotation (display-once, component-state only, never persisted)
 *   - logout-all (deletes every session row including this one)
 *
 * A failed re-auth is a generic 403 that never distinguishes which field was
 * wrong (`mapCredentialError` below): `mapApiError` handles any field-precise
 * 4xx the backend does name (e.g. new-password strength), and a 403 that
 * names no field falls back to the generic "Current password is incorrect"
 * message attached to the current-password input, matching the login form's
 * "never say which part was wrong" posture.
 */

const CREDENTIAL_FIELDS: ReadonlySet<string> = new Set([
  'current_password',
  'new_password',
]);

function mapCredentialError(
  error: unknown,
): { fieldErrors: Record<string, string>; formError: string | null } {
  const mapped = mapApiError(error, CREDENTIAL_FIELDS);
  if (
    error instanceof ApiRequestError &&
    error.status === 403 &&
    !mapped.fieldErrors.current_password
  ) {
    return {
      fieldErrors: {
        ...mapped.fieldErrors,
        current_password: 'Current password is incorrect.',
      },
      formError: null,
    };
  }
  return mapped;
}

export function Security() {
  const credentials = useAuthCredentials();

  return (
    <>
      <Toolbar title="Settings — Security" />
      <div className={styles.page}>
        {credentials.data && (
          <p className={styles.identity}>
            Signed in as <strong>{credentials.data.username}</strong>.
          </p>
        )}
        {credentials.isLoading && (
          <p className={styles.stateText}>Loading account status…</p>
        )}
        {credentials.isError && (
          <p className={styles.stateText}>Could not load account status.</p>
        )}

        <WebPasswordCard />
        <OpdsPasswordCard />
        <ApiKeyCard />
        <SessionsCard />
      </div>
    </>
  );
}

/* ---- Card 1: web password ------------------------------------------- */

function WebPasswordCard() {
  const changePassword = useChangePassword();

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const currentId = useId();
  const newId = useId();
  const confirmId = useId();

  const clearFeedback = () => {
    setFieldErrors({});
    setFormError(null);
    setSuccess(false);
  };

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    clearFeedback();

    if (!currentPassword || !newPassword || !confirmPassword) {
      setFormError('All fields are required.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setFieldErrors({ confirm_password: 'New passwords do not match.' });
      return;
    }

    changePassword.mutate(
      { current_password: currentPassword, new_password: newPassword },
      {
        onSuccess: () => {
          // Write-only fields; the acting session stays valid, so there is
          // nothing to navigate away from (FRG-AUTH-004 tail).
          setCurrentPassword('');
          setNewPassword('');
          setConfirmPassword('');
          setSuccess(true);
        },
        onError: (error) => {
          const mapped = mapCredentialError(error);
          setFieldErrors(mapped.fieldErrors);
          setFormError(mapped.formError);
        },
      },
    );
  };

  const saving = changePassword.isPending;

  return (
    <section className={styles.card} data-testid="web-password-card">
      <h2 className={styles.cardHeading}>Web Password</h2>
      <p className={styles.cardHelp}>
        Change the password used to sign in to this UI. You will stay signed
        in on this device; every other active session is signed out.
      </p>
      <form className={styles.form} onSubmit={onSubmit} noValidate>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={currentId}>
            Current password
          </label>
          <input
            id={currentId}
            className={styles.input}
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) => {
              setCurrentPassword(e.target.value);
              clearFeedback();
            }}
            disabled={saving}
          />
          {fieldErrors.current_password && (
            <span className={styles.fieldError} role="alert">
              {fieldErrors.current_password}
            </span>
          )}
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={newId}>
            New password
          </label>
          <input
            id={newId}
            className={styles.input}
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => {
              setNewPassword(e.target.value);
              clearFeedback();
            }}
            disabled={saving}
          />
          {fieldErrors.new_password && (
            <span className={styles.fieldError} role="alert">
              {fieldErrors.new_password}
            </span>
          )}
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={confirmId}>
            Confirm new password
          </label>
          <input
            id={confirmId}
            className={styles.input}
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => {
              setConfirmPassword(e.target.value);
              clearFeedback();
            }}
            disabled={saving}
          />
          {fieldErrors.confirm_password && (
            <span className={styles.fieldError} role="alert">
              {fieldErrors.confirm_password}
            </span>
          )}
        </div>
        {formError && (
          <div className={styles.formError} role="alert">
            {formError}
          </div>
        )}
        {success && (
          <div className={styles.successBanner} role="status">
            Password changed.
          </div>
        )}
        <div className={styles.actions}>
          <button type="submit" className={styles.button} disabled={saving}>
            {saving ? 'Changing…' : 'Change Password'}
          </button>
        </div>
      </form>
    </section>
  );
}

/* ---- Card 2: OPDS password -------------------------------------------- */

function OpdsPasswordCard() {
  const changeOpdsPassword = useChangeOpdsPassword();

  const [adminPassword, setAdminPassword] = useState('');
  const [newOpdsPassword, setNewOpdsPassword] = useState('');
  const [confirmOpdsPassword, setConfirmOpdsPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const adminId = useId();
  const newId = useId();
  const confirmId = useId();

  const clearFeedback = () => {
    setFieldErrors({});
    setFormError(null);
    setSuccess(false);
  };

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    clearFeedback();

    if (!adminPassword || !newOpdsPassword || !confirmOpdsPassword) {
      setFormError('All fields are required.');
      return;
    }
    if (newOpdsPassword !== confirmOpdsPassword) {
      setFieldErrors({ confirm_password: 'New passwords do not match.' });
      return;
    }

    changeOpdsPassword.mutate(
      { current_password: adminPassword, new_password: newOpdsPassword },
      {
        onSuccess: () => {
          setAdminPassword('');
          setNewOpdsPassword('');
          setConfirmOpdsPassword('');
          setSuccess(true);
        },
        onError: (error) => {
          const mapped = mapCredentialError(error);
          setFieldErrors(mapped.fieldErrors);
          setFormError(mapped.formError);
        },
      },
    );
  };

  const saving = changeOpdsPassword.isPending;

  return (
    <section className={styles.card} data-testid="opds-password-card">
      <h2 className={styles.cardHeading}>OPDS Password</h2>
      <p className={styles.cardHelp}>
        Reader apps (e.g. Panels) connect to the OPDS catalog with your web
        username and this separate password, over HTTP Basic auth. Changing
        it does not sign you out of the web UI — each reader app will simply
        re-prompt for credentials the next time it syncs.
      </p>
      <form className={styles.form} onSubmit={onSubmit} noValidate>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={adminId}>
            Current admin password
          </label>
          <input
            id={adminId}
            className={styles.input}
            type="password"
            autoComplete="current-password"
            value={adminPassword}
            onChange={(e) => {
              setAdminPassword(e.target.value);
              clearFeedback();
            }}
            disabled={saving}
          />
          {fieldErrors.current_password && (
            <span className={styles.fieldError} role="alert">
              {fieldErrors.current_password}
            </span>
          )}
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={newId}>
            New OPDS password
          </label>
          <input
            id={newId}
            className={styles.input}
            type="password"
            autoComplete="new-password"
            value={newOpdsPassword}
            onChange={(e) => {
              setNewOpdsPassword(e.target.value);
              clearFeedback();
            }}
            disabled={saving}
          />
          {fieldErrors.new_password && (
            <span className={styles.fieldError} role="alert">
              {fieldErrors.new_password}
            </span>
          )}
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={confirmId}>
            Confirm new OPDS password
          </label>
          <input
            id={confirmId}
            className={styles.input}
            type="password"
            autoComplete="new-password"
            value={confirmOpdsPassword}
            onChange={(e) => {
              setConfirmOpdsPassword(e.target.value);
              clearFeedback();
            }}
            disabled={saving}
          />
          {fieldErrors.confirm_password && (
            <span className={styles.fieldError} role="alert">
              {fieldErrors.confirm_password}
            </span>
          )}
        </div>
        {formError && (
          <div className={styles.formError} role="alert">
            {formError}
          </div>
        )}
        {success && (
          <div className={styles.successBanner} role="status">
            OPDS password changed. Reader apps will re-prompt.
          </div>
        )}
        <div className={styles.actions}>
          <button type="submit" className={styles.button} disabled={saving}>
            {saving ? 'Changing…' : 'Change OPDS Password'}
          </button>
        </div>
      </form>
    </section>
  );
}

/* ---- Card 3: API key --------------------------------------------------- */

function ApiKeyCard() {
  const rotateApiKey = useRotateApiKey();

  const [confirming, setConfirming] = useState(false);
  const [rotatePassword, setRotatePassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  // The raw key lives ONLY here, in component state — never in a query
  // cache, never in localStorage/sessionStorage. Setting it back to null on
  // modal dismiss is what makes it non-recoverable (FRG-AUTH-007): there is
  // no other reference to the string anywhere in the app after that.
  const [rawKey, setRawKey] = useState<string | null>(null);

  const rotatePasswordId = useId();

  const openConfirm = () => {
    setFieldErrors({});
    setFormError(null);
    setRotatePassword('');
    setConfirming(true);
  };

  const closeConfirm = () => {
    setConfirming(false);
    setRotatePassword('');
    setFieldErrors({});
    setFormError(null);
  };

  const onConfirmRotate = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setFieldErrors({});
    setFormError(null);
    if (!rotatePassword) {
      setFormError('Current password is required.');
      return;
    }
    rotateApiKey.mutate(
      { current_password: rotatePassword },
      {
        onSuccess: (res) => {
          setConfirming(false);
          setRotatePassword('');
          setRawKey(res.api_key);
        },
        onError: (error) => {
          const mapped = mapCredentialError(error);
          setFieldErrors(mapped.fieldErrors);
          setFormError(mapped.formError);
        },
      },
    );
  };

  const rotating = rotateApiKey.isPending;

  return (
    <section className={styles.card} data-testid="api-key-card">
      <h2 className={styles.cardHeading}>API Key</h2>
      <p className={styles.cardHelp}>
        The API key authenticates external calls without a browser session.
        It is shown only once, immediately after it is first generated or
        rotated — foragerr never displays it again afterward. Rotating
        replaces it immediately; anything still using the old key stops
        working right away.
      </p>
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.buttonSecondary}
          onClick={openConfirm}
        >
          Rotate API Key
        </button>
      </div>

      {confirming && (
        <Modal
          title="Rotate API Key"
          label="Rotate API key"
          onClose={closeConfirm}
          footer={
            <>
              <button
                type="button"
                className={styles.buttonSecondary}
                onClick={closeConfirm}
              >
                Cancel
              </button>
              <button
                type="submit"
                form="rotate-api-key-form"
                className={styles.buttonDanger}
                disabled={rotating}
              >
                {rotating ? 'Rotating…' : 'Rotate'}
              </button>
            </>
          }
        >
          <form id="rotate-api-key-form" onSubmit={onConfirmRotate} noValidate>
            <p className={styles.confirmIntro}>
              The current API key will <strong>stop working immediately</strong>.
              Enter your admin password to confirm.
            </p>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={rotatePasswordId}>
                Current password
              </label>
              <input
                id={rotatePasswordId}
                className={styles.input}
                type="password"
                autoComplete="current-password"
                value={rotatePassword}
                onChange={(e) => {
                  setRotatePassword(e.target.value);
                  setFieldErrors({});
                  setFormError(null);
                }}
                disabled={rotating}
              />
              {fieldErrors.current_password && (
                <span className={styles.fieldError} role="alert">
                  {fieldErrors.current_password}
                </span>
              )}
            </div>
            {formError && (
              <div className={styles.formError} role="alert">
                {formError}
              </div>
            )}
          </form>
        </Modal>
      )}

      {rawKey && (
        <KeyDisplayModal apiKey={rawKey} onClose={() => setRawKey(null)} />
      )}
    </section>
  );
}

function KeyDisplayModal({
  apiKey,
  onClose,
}: {
  apiKey: string;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const onCopy = () => {
    navigator.clipboard
      ?.writeText(apiKey)
      .then(() => setCopied(true))
      .catch(() => {
        // Clipboard access can be denied/unavailable — the key is still
        // visible and selectable in the field below.
      });
  };

  return (
    <Modal
      title="New API Key"
      label="New API key"
      onClose={onClose}
      footer={
        <button type="button" className={styles.button} onClick={onClose}>
          Done
        </button>
      }
    >
      <div className={styles.keyRow}>
        <input
          className={styles.keyValue}
          type="text"
          readOnly
          value={apiKey}
          aria-label="New API key"
          onFocus={(e) => e.currentTarget.select()}
        />
        <button
          type="button"
          className={styles.buttonSecondary}
          onClick={onCopy}
        >
          Copy
        </button>
      </div>
      {copied && (
        <p className={styles.copiedHint} role="status">
          Copied to clipboard.
        </p>
      )}
      <p className={styles.keyWarning} role="alert">
        You won&apos;t see this key again — copy it now.
      </p>
    </Modal>
  );
}

/* ---- Card 4: sessions --------------------------------------------------- */

function SessionsCard() {
  const logoutAll = useLogoutAll();
  const navigate = useNavigate();
  const setUnauthenticated = useAuthStore((s) => s.setUnauthenticated);

  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onConfirm = () => {
    setError(null);
    logoutAll.mutate(undefined, {
      onSuccess: () => {
        setConfirming(false);
        // Mirrors LogoutButton: flip the store directly rather than waiting
        // for some later request to 401 into the fetcher's interceptor — the
        // acting session is dead now, so land on /login immediately.
        setUnauthenticated();
        navigate('/login', { replace: true });
      },
      onError: (err) => {
        setError(err instanceof Error ? err.message : 'Logout failed.');
      },
    });
  };

  const loggingOut = logoutAll.isPending;

  return (
    <section className={styles.card} data-testid="sessions-card">
      <h2 className={styles.cardHeading}>Sessions</h2>
      <p className={styles.cardHelp}>
        Sign out of every device, including this one — useful if a session was
        left open on a shared or lost device.
      </p>
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.buttonDanger}
          onClick={() => {
            setError(null);
            setConfirming(true);
          }}
        >
          Log Out All Devices
        </button>
      </div>
      {error && (
        <div className={styles.formError} role="alert">
          {error}
        </div>
      )}

      {confirming && (
        <Modal
          title="Log Out All Devices"
          label="Log out all devices"
          onClose={() => setConfirming(false)}
          footer={
            <>
              <button
                type="button"
                className={styles.buttonSecondary}
                onClick={() => setConfirming(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={styles.buttonDanger}
                disabled={loggingOut}
                onClick={onConfirm}
              >
                {loggingOut ? 'Logging out…' : 'Log Out All Devices'}
              </button>
            </>
          }
        >
          <p className={styles.confirmIntro}>
            This logs out <strong>every device</strong>, including this one.
            You will need to sign in again.
          </p>
        </Modal>
      )}
    </section>
  );
}
