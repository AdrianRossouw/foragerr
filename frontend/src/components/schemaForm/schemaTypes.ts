/*
 * Types for the backend fields[] schema contract (FRG-UI-008 / FRG-API-009).
 *
 * Mirrors `foragerr.indexers.schema.FieldSpec` — the full Sonarr Field union
 * the backend derives from each implementation's Pydantic settings model:
 *   order, name, type, label, help, required, secret, selectOptions, advanced.
 *
 * Field NAMES are backend settings names verbatim (snake_case, e.g. `base_url`)
 * because the settings payload keys must round-trip into the Pydantic contract
 * unchanged. Secret fields are flagged and NEVER carry a value in any response
 * (write-only by construction).
 */

export type SchemaFieldType =
  | 'textbox'
  | 'number'
  | 'checkbox'
  | 'select'
  | 'password';

export interface SchemaSelectOption {
  value: string | number;
  name: string;
}

export interface SchemaField {
  order: number;
  name: string;
  type: SchemaFieldType;
  label: string;
  help: string;
  required: boolean;
  secret: boolean;
  advanced: boolean;
  selectOptions: SchemaSelectOption[];
}

/** One implementation's schema template from GET /api/v1/{kind}/schema. */
export interface ImplementationSchema {
  implementation: string;
  name: string;
  protocol: string;
  fields: SchemaField[];
}

/** The value union a schema-driven field can hold. */
export type FieldValue = string | number | boolean | Array<string | number>;

export type FieldValues = Record<string, FieldValue | undefined>;
