import type {
  FieldValues,
  SchemaField,
} from '../schemaForm/schemaTypes';

/*
 * Provider-settings contracts shared by every provider kind (FRG-UI-008/009).
 *
 * A "provider" is one configured row of a provider table (indexers,
 * download clients — notifiers in M2). Row-level field names are the backend
 * column names verbatim (snake_case, matching the API's resource-field
 * convention); `settings` is the implementation's public settings dict, in
 * which secret values are NEVER present (write-only, FRG-API-009).
 */

export interface ProviderResource {
  id: number;
  name: string;
  implementation: string;
  protocol: string;
  enabled: boolean;
  priority: number;
  /** Indexer usage toggles (FRG-IDX-002); absent for other kinds. */
  enable_rss?: boolean;
  enable_auto?: boolean;
  enable_interactive?: boolean;
  /** Download-client flag (FRG-DL-002); absent for other kinds. */
  remove_completed_downloads?: boolean;
  /** Public settings — secrets dropped server-side, never echoed. */
  settings: FieldValues;
}

/** Structured pass result from POST /api/v1/{kind}/test. */
export interface ProviderTestResult {
  success: boolean;
  message: string;
  warnings?: string[];
}

export type ChipTone = 'success' | 'danger' | 'warning' | 'muted';

export interface ProviderChip {
  label: string;
  tone: ChipTone;
}

/**
 * Everything that distinguishes one provider kind from another — pure DATA.
 * Row-level fields are expressed as SchemaField[] so the ONE generic renderer
 * draws them too; a new provider kind is a new config object, never new form
 * code (the FRG-UI-009 audit test enforces this).
 */
export interface ProviderKindConfig {
  /** API path segment and query-key root: 'indexer' | 'downloadclient'. */
  key: string;
  /** Page/section title, e.g. 'Indexers'. */
  title: string;
  /** Modal noun, e.g. 'Indexer'. */
  singular: string;
  /** REST base, e.g. '/api/v1/indexer'. */
  apiBase: string;
  /** Provider-row fields (name, toggles, priority) rendered by SchemaForm. */
  rowFields: SchemaField[];
  /** Initial row values for a new provider. */
  rowDefaults: FieldValues;
  /** Status chips shown on a configured provider's card. */
  chips: (provider: ProviderResource) => ProviderChip[];
}
