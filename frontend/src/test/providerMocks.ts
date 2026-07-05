import type { ImplementationSchema } from '../components/schemaForm/schemaTypes';
import type { ProviderResource } from '../components/settings/providerTypes';

/*
 * Typed mocks for the provider settings screens (FRG-UI-008/009). The schema
 * fields[] mirror the REAL backend contracts verbatim:
 *   - newznab:  foragerr.indexers.settings.NewznabSettings
 *   - sabnzbd:  foragerr.downloads.settings.SabnzbdSettings
 *   - ddl:      foragerr.downloads.settings.BuiltinDdlSettings
 * (as derived by foragerr.indexers.schema.schema_for). Secret values are NEVER
 * present in provider rows — write-only by construction.
 */

export const mockIndexerSchemas: ImplementationSchema[] = [
  {
    implementation: 'newznab',
    name: 'Newznab',
    protocol: 'usenet',
    fields: [
      {
        order: 0,
        name: 'base_url',
        type: 'textbox',
        label: 'URL',
        help: 'Base URL of the Newznab indexer, e.g. https://api.dognzb.cr',
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
        help: "Your account's Newznab API key.",
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
        help: 'Newznab categories to search; defaults to 7030 (Books/Comics).',
        required: false,
        secret: false,
        advanced: false,
        selectOptions: [{ value: 7030, name: 'Books/Comics (7030)' }],
      },
      {
        order: 3,
        name: 'additional_parameters',
        type: 'textbox',
        label: 'Additional Parameters',
        help: 'Extra query parameters appended verbatim, e.g. &extended=1.',
        required: false,
        secret: false,
        advanced: true,
        selectOptions: [],
      },
    ],
  },
];

export const mockDownloadClientSchemas: ImplementationSchema[] = [
  {
    implementation: 'sabnzbd',
    name: 'SABnzbd',
    protocol: 'usenet',
    fields: [
      {
        order: 0,
        name: 'base_url',
        type: 'textbox',
        label: 'URL',
        help: 'Base URL of the SABnzbd host, e.g. http://192.168.1.10:8080',
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
        help: 'SABnzbd API key (Config → General → API Key).',
        required: true,
        secret: true,
        advanced: false,
        selectOptions: [],
      },
      {
        order: 2,
        name: 'category',
        type: 'textbox',
        label: 'Category',
        help: "SABnzbd category grabs are filed under; polling is filtered to it. Defaults to 'comics'.",
        required: false,
        secret: false,
        advanced: false,
        selectOptions: [],
      },
      {
        order: 3,
        name: 'priority',
        type: 'number',
        label: 'Priority',
        help: 'SABnzbd priority for added downloads: -100 Default, -1 Low, 0 Normal, 1 High, 2 Force.',
        required: false,
        secret: false,
        advanced: true,
        selectOptions: [
          { value: -100, name: 'Default' },
          { value: -1, name: 'Low' },
          { value: 0, name: 'Normal' },
          { value: 1, name: 'High' },
          { value: 2, name: 'Force' },
        ],
      },
    ],
  },
  {
    implementation: 'ddl',
    name: 'Built-in DDL',
    protocol: 'ddl',
    fields: [
      {
        order: 0,
        name: 'host_priority',
        type: 'textbox',
        label: 'Host Priority',
        help: 'Comma-separated download-host preference order. Earlier hosts are tried first.',
        required: false,
        secret: false,
        advanced: true,
        selectOptions: [],
      },
      {
        order: 1,
        name: 'prefer_upscaled',
        type: 'checkbox',
        label: 'Prefer Upscaled',
        help: 'Prefer HD-Upscaled quality links when a post offers several quality tiers.',
        required: false,
        secret: false,
        advanced: true,
        selectOptions: [],
      },
    ],
  },
];

export const mockIndexers: ProviderResource[] = [
  {
    id: 1,
    name: 'DogNZB',
    implementation: 'newznab',
    protocol: 'usenet',
    enabled: true,
    priority: 25,
    enable_rss: true,
    enable_auto: true,
    enable_interactive: true,
    // Public settings: api_key (secret) deliberately ABSENT — write-only.
    settings: { base_url: 'https://api.dognzb.cr', categories: [7030] },
  },
];

export const mockDownloadClients: ProviderResource[] = [
  {
    id: 1,
    name: 'SABnzbd',
    implementation: 'sabnzbd',
    protocol: 'usenet',
    enabled: true,
    priority: 25,
    remove_completed_downloads: true,
    // Public settings: api_key (secret) deliberately ABSENT — write-only.
    settings: { base_url: 'http://sab:8080', category: 'comics', priority: -100 },
  },
];
