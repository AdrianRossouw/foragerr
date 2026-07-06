import type { SchemaField } from '../schemaForm/schemaTypes';
import type { ProviderChip, ProviderKindConfig, ProviderResource } from './providerTypes';

/*
 * The provider kinds (FRG-UI-008 indexers, FRG-UI-009 download clients).
 *
 * DATA ONLY — no JSX, no form code. Each kind config differs from the next by
 * row-field metadata and card chips; the screens, modal, and renderer are the
 * same generic components. Notifiers (M2) become a third object here.
 */

function checkbox(
  order: number,
  name: string,
  label: string,
  help: string,
): SchemaField {
  return {
    order,
    name,
    type: 'checkbox',
    label,
    help,
    required: false,
    secret: false,
    advanced: false,
    selectOptions: [],
  };
}

const nameField: SchemaField = {
  order: 0,
  name: 'name',
  type: 'textbox',
  label: 'Name',
  help: '',
  required: true,
  secret: false,
  advanced: false,
  selectOptions: [],
};

export const indexerKind: ProviderKindConfig = {
  key: 'indexer',
  title: 'Indexers',
  singular: 'Indexer',
  apiBase: '/api/v1/indexer',
  rowFields: [
    nameField,
    checkbox(
      1,
      'enable_rss',
      'Enable RSS',
      'Used when foragerr periodically looks for releases via RSS sync.',
    ),
    checkbox(
      2,
      'enable_auto',
      'Enable Automatic Search',
      'Used when automatic searches are performed via the UI or by foragerr.',
    ),
    checkbox(
      3,
      'enable_interactive',
      'Enable Interactive Search',
      'Used when an interactive search is performed.',
    ),
    {
      order: 4,
      name: 'priority',
      type: 'number',
      label: 'Indexer Priority',
      help: 'Priority from 1 (highest) to 50 (lowest). Default: 25.',
      required: false,
      secret: false,
      advanced: true,
      selectOptions: [],
    },
  ],
  rowDefaults: {
    name: '',
    enabled: true,
    enable_rss: true,
    enable_auto: true,
    enable_interactive: true,
    priority: 25,
  },
  chips: (p: ProviderResource): ProviderChip[] => {
    if (!p.enabled) return [{ label: 'Disabled', tone: 'danger' }];
    const chips: ProviderChip[] = [];
    if (p.enable_rss) chips.push({ label: 'RSS', tone: 'success' });
    if (p.enable_auto) chips.push({ label: 'Automatic Search', tone: 'success' });
    if (p.enable_interactive)
      chips.push({ label: 'Interactive Search', tone: 'success' });
    return chips;
  },
};

export const downloadClientKind: ProviderKindConfig = {
  key: 'downloadclient',
  title: 'Download Clients',
  singular: 'Download Client',
  apiBase: '/api/v1/downloadclient',
  rowFields: [
    nameField,
    checkbox(1, 'enabled', 'Enable', 'Enable this download client.'),
    checkbox(
      2,
      'remove_completed_downloads',
      'Remove Completed',
      'Remove imported downloads from the download client history.',
    ),
  ],
  rowDefaults: {
    name: '',
    enabled: true,
    remove_completed_downloads: true,
  },
  chips: (p: ProviderResource): ProviderChip[] =>
    p.enabled
      ? [{ label: 'Enabled', tone: 'success' }]
      : [{ label: 'Disabled', tone: 'danger' }],
};
