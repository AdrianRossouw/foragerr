import { useState } from 'react';
import { SchemaForm } from 'foragerr-frontend';

/*
 * SchemaForm (FRG-UI-008) — the ONE generic schema-driven form renderer.
 * Driven by the backend fields[] union (textbox / number / checkbox / select /
 * password), it draws every provider-settings control in the app. Fixtures use
 * a realistic Newznab indexer schema; secrets are write-only and never carry a
 * real value.
 */

type Field = {
  order: number;
  name: string;
  type: 'textbox' | 'number' | 'checkbox' | 'select' | 'password';
  label: string;
  help: string;
  required: boolean;
  secret: boolean;
  advanced: boolean;
  selectOptions: { value: string | number; name: string }[];
};

const newznabFields: Field[] = [
  {
    order: 0,
    name: 'base_url',
    type: 'textbox',
    label: 'URL',
    help: 'The base URL of the Newznab indexer, e.g. https://dognzb.cr',
    required: true,
    secret: false,
    advanced: false,
    selectOptions: [],
  },
  {
    order: 1,
    name: 'api_key',
    type: 'password',
    label: 'API Key',
    help: 'Your indexer API key.',
    required: true,
    secret: true,
    advanced: false,
    selectOptions: [],
  },
  {
    order: 2,
    name: 'categories',
    type: 'select',
    label: 'Categories',
    help: 'Newznab categories to search for comics.',
    required: false,
    secret: false,
    advanced: false,
    selectOptions: [
      { value: 7030, name: 'Books/Comics (7030)' },
      { value: 7000, name: 'Books (7000)' },
      { value: 7020, name: 'Books/EBook (7020)' },
    ],
  },
  {
    order: 3,
    name: 'early_download_limit',
    type: 'number',
    label: 'Early Download Limit',
    help: 'Days before an issue release to start searching.',
    required: false,
    secret: false,
    advanced: false,
    selectOptions: [],
  },
  {
    order: 4,
    name: 'verify_ssl',
    type: 'checkbox',
    label: 'Verify SSL',
    help: "Verify the indexer's TLS certificate on every request.",
    required: false,
    secret: false,
    advanced: false,
    selectOptions: [],
  },
  {
    order: 5,
    name: 'api_path',
    type: 'textbox',
    label: 'API Path',
    help: 'Path to the Newznab API, usually /api.',
    required: false,
    secret: false,
    advanced: true,
    selectOptions: [],
  },
];

/** A fresh Newznab indexer form: text, password, multi-select, number, toggle. */
export const IndexerConfigForm = () => {
  const [values, setValues] = useState<Record<string, unknown>>({
    base_url: 'https://dognzb.cr',
    categories: [7030],
    early_download_limit: 7,
    verify_ssl: true,
  });
  return (
    <div style={{ maxWidth: 560 }}>
      <SchemaForm
        fields={newznabFields}
        values={values}
        onChange={(name: string, value: unknown) =>
          setValues((prev) => ({ ...prev, [name]: value }))
        }
      />
    </div>
  );
};

/** Editing an existing indexer: the stored API key stays write-only — the input
 *  renders empty with the "•••••••• — leave blank to keep" placeholder, and the
 *  saved categories show as chips. Advanced fields revealed. */
export const StoredSecretAndSelection = () => {
  const [values, setValues] = useState<Record<string, unknown>>({
    base_url: 'https://api.nzb.su',
    categories: [7030, 7000],
    early_download_limit: 3,
    verify_ssl: true,
    api_path: '/api',
  });
  return (
    <div style={{ maxWidth: 560 }}>
      <SchemaForm
        fields={newznabFields}
        values={values}
        onChange={(name: string, value: unknown) =>
          setValues((prev) => ({ ...prev, [name]: value }))
        }
        storedSecrets={new Set(['api_key'])}
        showAdvanced
      />
    </div>
  );
};

/** Field-precise validation: backend errors[] surfaced inline under each field
 *  (a hidden advanced field carrying an error is force-shown — no silent fails). */
export const WithValidationErrors = () => {
  const [values, setValues] = useState<Record<string, unknown>>({
    base_url: 'dognzb.cr',
    categories: [7030],
    verify_ssl: false,
  });
  return (
    <div style={{ maxWidth: 560 }}>
      <SchemaForm
        fields={newznabFields}
        values={values}
        onChange={(name: string, value: unknown) =>
          setValues((prev) => ({ ...prev, [name]: value }))
        }
        errors={{
          base_url: 'Must be an http(s) URL.',
          api_key: 'API key is required.',
          api_path: 'Path must start with a slash.',
        }}
      />
    </div>
  );
};
