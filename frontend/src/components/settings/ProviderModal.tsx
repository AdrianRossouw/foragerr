import { useMemo, useState, type KeyboardEvent } from 'react';
import { SchemaForm } from '../schemaForm/SchemaForm';
import { mapApiError } from './apiErrors';
import type {
  FieldValue,
  FieldValues,
  ImplementationSchema,
  SchemaField,
} from '../schemaForm/schemaTypes';
import {
  useDeleteProvider,
  useSaveProvider,
  useTestProvider,
} from './providerHooks';
import type {
  ProviderKindConfig,
  ProviderResource,
  ProviderTestResult,
} from './providerTypes';
import styles from './settings.module.css';

/*
 * P6 add/edit provider modal (FRG-UI-008/009) — generic over the kind.
 *
 * The body is rendered ENTIRELY by the schema-form renderer: one SchemaForm
 * for the kind's row fields (name/toggles/priority — data from the kind
 * config) and one for the implementation's fields[] schema. Footer copies
 * Sonarr: Delete (danger, left) | Test, Cancel, Save (accent, right).
 *
 * Secrets are write-only: stored values never arrive from the API, the inputs
 * start empty with "set" placeholder semantics, and a blank secret on save is
 * OMITTED from the settings payload (meaning "keep the stored value").
 */

interface ModalProps {
  kind: ProviderKindConfig;
  schema: ImplementationSchema;
  /** Present when editing an existing provider. */
  provider?: ProviderResource;
  showAdvanced: boolean;
  onClose: () => void;
}

function initialRowValues(
  kind: ProviderKindConfig,
  provider?: ProviderResource,
): FieldValues {
  if (!provider) return { ...kind.rowDefaults };
  const values: FieldValues = {};
  for (const name of Object.keys(kind.rowDefaults)) {
    const stored = (provider as unknown as Record<string, unknown>)[name];
    values[name] =
      stored === undefined ? kind.rowDefaults[name] : (stored as FieldValue);
  }
  return values;
}

/**
 * Build the settings payload. A never-set field (undefined) is always omitted.
 * Blank values are dropped ONLY for secret fields — that is the write-only
 * round trip where blank means "keep the stored value". A blank NON-secret
 * field is sent verbatim (including '') so it can actually be CLEARED; dropping
 * it would silently leave the backend's old value in place.
 */
function settingsPayload(fields: SchemaField[], values: FieldValues): FieldValues {
  const out: FieldValues = {} as FieldValues;
  for (const field of fields) {
    const value = values[field.name];
    if (value === undefined) continue;
    if (field.secret) {
      if (value === '') continue;
      if (Array.isArray(value) && value.length === 0) continue;
    }
    out[field.name] = value;
  }
  return out;
}

export function ProviderModal({
  kind,
  schema,
  provider,
  showAdvanced,
  onClose,
}: ModalProps) {
  const editing = provider !== undefined;
  const [rowValues, setRowValues] = useState<FieldValues>(() =>
    initialRowValues(kind, provider),
  );
  const [settingsValues, setSettingsValues] = useState<FieldValues>(() => {
    // Secrets are write-only and must never arrive from the API. Defense in
    // depth: if the backend ever regressed and echoed one, drop it here so it
    // can never flow into a password input's value.
    const seed: FieldValues = { ...(provider?.settings ?? {}) };
    for (const field of schema.fields) {
      if (field.secret) delete seed[field.name];
    }
    return seed;
  });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const save = useSaveProvider(kind);
  const remove = useDeleteProvider(kind);
  const test = useTestProvider(kind);

  // An existing provider's secret fields are stored server-side (they are
  // required at creation and never echoed back) — placeholder semantics.
  const storedSecrets = useMemo(
    () =>
      new Set(
        editing ? schema.fields.filter((f) => f.secret).map((f) => f.name) : [],
      ),
    [editing, schema],
  );

  const knownFields = useMemo(
    () =>
      new Set([
        ...kind.rowFields.map((f) => f.name),
        ...schema.fields.map((f) => f.name),
      ]),
    [kind, schema],
  );

  const clearFeedback = () => {
    setFieldErrors({});
    setFormError(null);
    setTestResult(null);
  };

  const onRowChange = (name: string, value: FieldValue) => {
    clearFeedback();
    setRowValues((prev) => ({ ...prev, [name]: value }));
  };

  const onSettingsChange = (name: string, value: FieldValue) => {
    clearFeedback();
    setSettingsValues((prev) => ({ ...prev, [name]: value }));
  };

  const onFailure = (error: unknown) => {
    const mapped = mapApiError(error, knownFields);
    setFieldErrors(mapped.fieldErrors);
    setFormError(mapped.formError);
  };

  const onTest = () => {
    clearFeedback();
    test.mutate(
      {
        implementation: schema.implementation,
        settings: settingsPayload(schema.fields, settingsValues),
      },
      { onSuccess: setTestResult, onError: onFailure },
    );
  };

  const onSave = () => {
    clearFeedback();
    save.mutate(
      {
        id: provider?.id,
        body: {
          ...rowValues,
          implementation: schema.implementation,
          settings: settingsPayload(schema.fields, settingsValues),
        },
      },
      { onSuccess: onClose, onError: onFailure },
    );
  };

  const onDelete = () => {
    if (!provider) return;
    if (!confirmingDelete) {
      setConfirmingDelete(true);
      return;
    }
    remove.mutate(provider.id, { onSuccess: onClose, onError: onFailure });
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
  };

  const title = `${editing ? 'Edit' : 'Add'} ${kind.singular} — ${schema.name}`;

  return (
    <div className={styles.overlay} onClick={onClose} onKeyDown={onKeyDown}>
      <div
        className={styles.modal}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>{title}</span>
          <button
            type="button"
            className={styles.iconButton}
            aria-label="Close"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <div className={styles.modalBody}>
          <SchemaForm
            fields={kind.rowFields}
            values={rowValues}
            onChange={onRowChange}
            errors={fieldErrors}
            showAdvanced={showAdvanced}
          />
          <SchemaForm
            fields={schema.fields}
            values={settingsValues}
            onChange={onSettingsChange}
            errors={fieldErrors}
            showAdvanced={showAdvanced}
            storedSecrets={storedSecrets}
          />
          {formError && (
            <div className={styles.formError} role="alert">
              {formError}
            </div>
          )}
          {testResult && (
            <div className={styles.testSuccess} data-testid="test-result">
              <div>{testResult.message}</div>
              {testResult.degraded && (
                <div className={styles.testWarning}>
                  {kind.singular} responded but with degraded capabilities
                </div>
              )}
              {testResult.warnings?.map((w) => (
                <div key={w} className={styles.testWarning}>
                  {w}
                </div>
              ))}
            </div>
          )}
        </div>
        <div className={styles.modalFooter}>
          {editing && (
            <button
              type="button"
              className={`${styles.button} ${styles.buttonDanger}`}
              onClick={onDelete}
              disabled={remove.isPending}
            >
              {confirmingDelete ? 'Confirm Delete' : 'Delete'}
            </button>
          )}
          <span className={styles.footerSpacer} />
          <button
            type="button"
            className={styles.button}
            onClick={onTest}
            disabled={test.isPending}
          >
            {test.isPending ? 'Testing…' : 'Test'}
          </button>
          <button type="button" className={styles.button} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={`${styles.button} ${styles.buttonPrimary}`}
            onClick={onSave}
            disabled={save.isPending}
          >
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
