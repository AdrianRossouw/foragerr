import { useId } from 'react';
import type {
  FieldValue,
  FieldValues,
  SchemaField,
  SchemaSelectOption,
} from './schemaTypes';
import styles from './SchemaForm.module.css';

/*
 * THE generic schema-form renderer (FRG-UI-008, reused verbatim for FRG-UI-009).
 *
 * Consumes the backend fields[] union (order/name/type/label/help/required/
 * secret/selectOptions/advanced) and renders each field through the widget map:
 *
 *   password / secret          -> write-only password input (stored value is
 *                                 NEVER echoed into the DOM; a placeholder
 *                                 signals "set — leave blank to keep")
 *   select (list-valued)       -> native multi-select + selected-value chips
 *   number|textbox w/ options  -> single select (typed values preserved)
 *   checkbox                   -> checkbox with its help text alongside (P13)
 *   number                     -> number input
 *   textbox                    -> text input
 *
 * This module is the ONLY place form controls may be rendered for provider
 * settings — the FRG-UI-009 audit test fails the build if any settings screen
 * grows form-element JSX outside this directory.
 */

export interface SchemaFormProps {
  fields: SchemaField[];
  values: FieldValues;
  onChange: (name: string, value: FieldValue) => void;
  /** Field-precise errors (backend `errors[]` mapped by field name). */
  errors?: Record<string, string>;
  /** Advanced fields are hidden unless enabled — except when they carry an
   * error, which must never be silently invisible (quiet-filter anti-goal). */
  showAdvanced?: boolean;
  /**
   * Names of secret fields that already have a stored server-side value.
   * Their inputs render empty with "set" placeholder semantics; leaving them
   * blank means "keep the stored secret".
   */
  storedSecrets?: ReadonlySet<string>;
}

export function SchemaForm({
  fields,
  values,
  onChange,
  errors = {},
  showAdvanced = false,
  storedSecrets,
}: SchemaFormProps) {
  const formId = useId();
  const ordered = [...fields].sort((a, b) => a.order - b.order);
  const visible = ordered.filter(
    (f) => showAdvanced || !f.advanced || errors[f.name] !== undefined,
  );

  return (
    <div className={styles.form} data-schema-form="true">
      {visible.map((field) => (
        <SchemaFormRow
          key={field.name}
          field={field}
          id={`${formId}-${field.name}`}
          value={values[field.name]}
          error={errors[field.name]}
          stored={field.secret && (storedSecrets?.has(field.name) ?? false)}
          onChange={(value) => onChange(field.name, value)}
        />
      ))}
    </div>
  );
}

interface RowProps {
  field: SchemaField;
  id: string;
  value: FieldValue | undefined;
  error: string | undefined;
  stored: boolean;
  onChange: (value: FieldValue) => void;
}

function SchemaFormRow({ field, id, value, error, stored, onChange }: RowProps) {
  const isCheckbox = field.type === 'checkbox';
  const labelClass = field.advanced
    ? `${styles.label} ${styles.labelAdvanced}`
    : styles.label;

  return (
    <div className={styles.row} data-testid={`schema-field-${field.name}`}>
      <label className={labelClass} htmlFor={id}>
        {field.label}
      </label>
      <div className={styles.control}>
        {isCheckbox ? (
          <div className={styles.checkboxWrap}>
            <input
              id={id}
              type="checkbox"
              className={styles.checkbox}
              checked={value === true}
              onChange={(e) => onChange(e.target.checked)}
            />
            {field.help && (
              <span className={styles.checkboxHelp}>{field.help}</span>
            )}
          </div>
        ) : (
          <ValueWidget
            field={field}
            id={id}
            value={value}
            stored={stored}
            onChange={onChange}
          />
        )}
        {!isCheckbox && field.help && (
          <div className={styles.help}>{field.help}</div>
        )}
        {stored && (
          <div className={styles.help} data-testid={`secret-hint-${field.name}`}>
            Currently set — leave blank to keep the stored value.
          </div>
        )}
        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

function ValueWidget({
  field,
  id,
  value,
  stored,
  onChange,
}: Omit<RowProps, 'error'>) {
  if (field.type === 'password' || field.secret) {
    // Write-only: the input never receives the stored secret, only what the
    // user types in this session. Placeholder dots signal "set but hidden".
    return (
      <input
        id={id}
        type="password"
        className={styles.input}
        autoComplete="new-password"
        value={typeof value === 'string' ? value : ''}
        placeholder={stored ? '••••••••' : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  if (field.type === 'select') {
    return (
      <MultiSelect
        id={id}
        options={field.selectOptions}
        value={Array.isArray(value) ? value : []}
        onChange={onChange}
      />
    );
  }

  if (field.selectOptions.length > 0) {
    // Scalar field with enumerated options (e.g. SABnzbd priority: a number
    // field carrying selectOptions) — a single select preserving typed values.
    const byKey = new Map(field.selectOptions.map((o) => [String(o.value), o.value]));
    return (
      <select
        id={id}
        className={styles.input}
        value={value === undefined ? '' : String(value)}
        onChange={(e) => onChange(byKey.get(e.target.value) ?? e.target.value)}
      >
        <option value="" disabled hidden />
        {field.selectOptions.map((o) => (
          <option key={String(o.value)} value={String(o.value)}>
            {o.name}
          </option>
        ))}
      </select>
    );
  }

  if (field.type === 'number') {
    return (
      <input
        id={id}
        type="number"
        className={styles.input}
        value={typeof value === 'number' ? value : ''}
        onChange={(e) =>
          onChange(e.target.value === '' ? '' : Number(e.target.value))
        }
      />
    );
  }

  return (
    <input
      id={id}
      type="text"
      className={styles.input}
      value={typeof value === 'string' || typeof value === 'number' ? String(value) : ''}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function MultiSelect({
  id,
  options,
  value,
  onChange,
}: {
  id: string;
  options: SchemaSelectOption[];
  value: Array<string | number>;
  onChange: (value: FieldValue) => void;
}) {
  const byKey = new Map(options.map((o) => [String(o.value), o.value]));
  const labelFor = (v: string | number) =>
    options.find((o) => String(o.value) === String(v))?.name ?? String(v);

  return (
    <div>
      <select
        id={id}
        multiple
        className={styles.input}
        size={Math.min(Math.max(options.length, 2), 4)}
        value={value.map(String)}
        onChange={(e) =>
          onChange(
            Array.from(e.target.selectedOptions, (o) => byKey.get(o.value) ?? o.value),
          )
        }
      >
        {options.map((o) => (
          <option key={String(o.value)} value={String(o.value)}>
            {o.name}
          </option>
        ))}
      </select>
      {value.length > 0 && (
        <div className={styles.chips}>
          {value.map((v) => (
            <span key={String(v)} className={styles.chip}>
              {labelFor(v)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
