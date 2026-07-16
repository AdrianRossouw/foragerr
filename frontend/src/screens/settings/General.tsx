import { useEffect, useState } from 'react';
import { Toolbar } from '../../components/Toolbar';
import { SchemaForm } from '../../components/schemaForm/SchemaForm';
import type {
  FieldValue,
  SchemaField,
} from '../../components/schemaForm/schemaTypes';
import { mapApiError } from '../../components/settings/apiErrors';
import type { ComicVineTestResult } from '../../api/types';
import {
  useComicVineConfig,
  usePutComicVineConfig,
  useTestComicVine,
} from './general/generalHooks';
import styles from './general/General.module.css';

/*
 * Settings -> General (FRG-UI-020).
 *
 * A BESPOKE single-form config-singleton screen (the MediaManagement save-bar
 * pattern), not the provider list+modal machinery — there is exactly one
 * global credential here, not a list of rows. The masked write-only key field
 * reuses the SHARED SchemaForm password widget (FRG-UI-009's pattern): the
 * stored key is never echoed into the DOM, a "currently set" hint renders
 * when one is stored, and a blank save keeps the stored value (a property of
 * the PUT endpoint itself, not special-cased here).
 *
 * The field's rendering is driven ENTIRELY by the resource's reported
 * `source` (FRG-API-018): `environment` renders a read-only explanatory note
 * instead of an editor the env var would silently shadow; `file`/`unset`
 * render the normal editable field, differing only in the stored-secret hint
 * and helper text.
 *
 * The Test button is a TEST-AFTER-SAVE affordance, not a pre-save probe like
 * the indexer/download-client Test: POST /comicvine/test carries no body and
 * exercises the currently-EFFECTIVE key (saved file value or env), so testing
 * an unsaved typed value would silently test the OLD key and misreport it as
 * the new one's status. It is disabled while the field has unsaved edits,
 * with a hint to save first. Its three outcomes mirror the provider Test
 * button's contract exactly (ProviderModal): success renders a pass message;
 * an auth failure (errors[].field = comicvine_api_key) attaches to the key
 * field via the SAME mapApiError path Save uses; a field-less reachability
 * failure renders as a form-level message — never a distinct always-shown
 * "test failed" box.
 */

const COMICVINE_KEY_FIELD: SchemaField = {
  order: 0,
  name: 'comicvine_api_key',
  type: 'password',
  label: 'ComicVine API Key',
  help: 'Used for series and issue metadata lookups. Get a free key from comicvine.gamespot.com/api.',
  required: false,
  secret: true,
  advanced: false,
  selectOptions: [],
};

const KNOWN_FIELDS: ReadonlySet<string> = new Set(['comicvine_api_key']);

export function General() {
  const configQuery = useComicVineConfig();
  const putConfig = usePutComicVineConfig();
  // A second, independent mutation for the ignored-publishers save so its
  // pending state does not entangle with the key Save (both hit PUT /general,
  // which handles the two fields independently — a save touching one leaves
  // the other alone server-side).
  const putIgnored = usePutComicVineConfig();
  const testComicVine = useTestComicVine();

  const [keyValue, setKeyValue] = useState('');
  const [ignoredValue, setIgnoredValue] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<ComicVineTestResult | null>(null);

  const config = configQuery.data;
  const source = config?.comicvine_api_key.source;
  const configured = config?.comicvine_api_key.configured ?? false;
  const envManaged = source === 'environment';

  const ignoredSource = config?.comicvine_ignored_publishers.source;
  const ignoredEnvManaged = ignoredSource === 'env';
  // Seed the editable list from the server value whenever it changes (initial
  // load, and after a save — the mutation writes the server's response back
  // into the cache, so the reseed matches what was just saved and never
  // clobbers in-progress edits between loads).
  const serverIgnored = config?.comicvine_ignored_publishers.value;
  useEffect(() => {
    if (serverIgnored !== undefined) setIgnoredValue(serverIgnored);
  }, [serverIgnored]);

  const clearFeedback = () => {
    setFieldErrors({});
    setFormError(null);
    setTestResult(null);
  };

  const onFailure = (error: unknown) => {
    const mapped = mapApiError(error, KNOWN_FIELDS);
    setFieldErrors(mapped.fieldErrors);
    setFormError(mapped.formError);
  };

  const onChange = (_name: string, value: FieldValue) => {
    clearFeedback();
    setKeyValue(typeof value === 'string' ? value : '');
  };

  const onSave = () => {
    clearFeedback();
    putConfig.mutate(
      { comicvine_api_key: keyValue },
      { onSuccess: () => setKeyValue(''), onError: onFailure },
    );
  };

  const onSaveIgnored = () => {
    clearFeedback();
    // A string (including '') sets the list; the key field is omitted, so the
    // stored key is untouched. Errors fold into the form-level message (the
    // list is not in KNOWN_FIELDS, so mapApiError routes them there).
    putIgnored.mutate(
      { comicvine_ignored_publishers: ignoredValue },
      { onError: onFailure },
    );
  };

  const onTest = () => {
    clearFeedback();
    testComicVine.mutate(undefined, {
      onSuccess: setTestResult,
      onError: onFailure,
    });
  };

  const saving = putConfig.isPending;
  const testing = testComicVine.isPending;
  // Test exercises the EFFECTIVE (already-saved) key, not this unsaved typed
  // value — testing while dirty would silently probe the OLD key and report
  // its status as if it belonged to what's in the field right now.
  const hasUnsavedEdits = keyValue !== '';

  return (
    <>
      <Toolbar
        title="Settings — General"
        actions={
          !envManaged && (
            <button
              type="button"
              className={styles.saveButton}
              disabled={saving}
              onClick={onSave}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          )
        }
      />
      <div className={styles.page}>
        {configQuery.isLoading && (
          <p className={styles.stateText}>Loading settings…</p>
        )}
        {configQuery.isError && (
          <p className={styles.stateText}>Could not load general settings.</p>
        )}

        {config && (
          <section className={styles.section}>
            <h2 className={styles.sectionHeading}>ComicVine</h2>

            {envManaged ? (
              <p
                className={styles.envNote}
                role="status"
                data-testid="comicvine-key-env-managed"
              >
                Set by the <code>FORAGERR_COMICVINE_API_KEY</code> environment
                variable — managed outside the UI. To change it, edit the
                environment variable and restart foragerr.
              </p>
            ) : (
              <>
                <SchemaForm
                  fields={[COMICVINE_KEY_FIELD]}
                  values={{ comicvine_api_key: keyValue }}
                  onChange={onChange}
                  errors={fieldErrors}
                  storedSecrets={
                    configured ? new Set(['comicvine_api_key']) : undefined
                  }
                />
                {!configured && (
                  <p
                    className={styles.sectionHelp}
                    data-testid="comicvine-key-unset-hint"
                  >
                    No ComicVine API key is configured yet. Metadata lookups
                    will fail until one is set.
                  </p>
                )}
              </>
            )}

            {formError && (
              <div className={styles.formError} role="alert">
                {formError}
              </div>
            )}

            <div>
              <button
                type="button"
                className={styles.button}
                disabled={testing || hasUnsavedEdits}
                onClick={onTest}
              >
                {testing ? 'Testing…' : 'Test'}
              </button>
              {hasUnsavedEdits && !envManaged && (
                <p
                  className={styles.sectionHelp}
                  data-testid="comicvine-test-disabled-hint"
                >
                  Save your changes before testing the new key.
                </p>
              )}
            </div>

            {testResult && (
              <div
                className={styles.testSuccess}
                data-testid="comicvine-test-result"
                role="status"
              >
                {testResult.message}
              </div>
            )}
          </section>
        )}

        {config && (
          <section className={styles.section}>
            <h2 className={styles.sectionHeading}>Ignored Publishers</h2>

            {ignoredEnvManaged ? (
              <p
                className={styles.envNote}
                role="status"
                data-testid="ignored-publishers-env-managed"
              >
                Set by the <code>FORAGERR_COMICVINE_IGNORED_PUBLISHERS</code>{' '}
                environment variable — managed outside the UI. To change it, edit
                the environment variable and restart foragerr.
              </p>
            ) : (
              <>
                <label className={styles.fieldLabel} htmlFor="ignored-publishers">
                  Publishers hidden from Add New search results
                </label>
                <textarea
                  id="ignored-publishers"
                  className={styles.textarea}
                  data-testid="ignored-publishers-input"
                  value={ignoredValue}
                  onChange={(e) => {
                    clearFeedback();
                    setIgnoredValue(e.target.value);
                  }}
                  rows={3}
                />
                <p className={styles.sectionHelp}>
                  Comma-separated publisher names — foreign-market reprint
                  imprints that otherwise outrank the original volume. An entry
                  containing <code>*</code> matches anywhere in the publisher
                  name (e.g. <code>Panini*</code> covers Panini
                  Verlag/España/France); any other entry matches exactly.
                  Hidden results are counted and stay recoverable per-search in
                  Add New. Saving an empty field hides nothing.
                </p>
                <button
                  type="button"
                  className={styles.saveButton}
                  data-testid="ignored-publishers-save"
                  disabled={putIgnored.isPending}
                  onClick={onSaveIgnored}
                >
                  {putIgnored.isPending ? 'Saving…' : 'Save ignored publishers'}
                </button>
              </>
            )}
          </section>
        )}
      </div>
    </>
  );
}
