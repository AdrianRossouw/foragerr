import { ProviderModal } from 'foragerr-frontend';

/*
 * ProviderModal (FRG-UI-008/009) — the schema-driven add/edit modal, shown here
 * in its OPEN state with a filled form. Its overlay is `position: fixed; inset:0`,
 * so a `transform`-containing wrapper with an explicit height keeps the modal
 * inside the preview cell instead of covering the whole sheet.
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

const f = (over: Partial<Field>): Field => ({
  order: 0,
  name: 'field',
  type: 'textbox',
  label: 'Field',
  help: '',
  required: false,
  secret: false,
  advanced: false,
  selectOptions: [],
  ...over,
});

const checkbox = (order: number, name: string, label: string, help: string): Field =>
  f({ order, name, type: 'checkbox', label, help });

const nameField = f({ order: 0, name: 'name', label: 'Name', required: true });

const indexerKind = {
  key: 'indexer',
  title: 'Indexers',
  singular: 'Indexer',
  apiBase: '/api/v1/indexer',
  rowFields: [
    nameField,
    checkbox(1, 'enable_rss', 'Enable RSS', 'Used during periodic RSS sync.'),
    checkbox(2, 'enable_auto', 'Enable Automatic Search', 'Used for automatic searches.'),
    checkbox(3, 'enable_interactive', 'Enable Interactive Search', 'Used for interactive searches.'),
    f({
      order: 4,
      name: 'priority',
      type: 'number',
      label: 'Indexer Priority',
      help: 'Priority from 1 (highest) to 50 (lowest). Default: 25.',
      advanced: true,
    }),
  ],
  rowDefaults: {
    name: '',
    enabled: true,
    enable_rss: true,
    enable_auto: true,
    enable_interactive: true,
    priority: 25,
  },
  chips: () => [],
};

const downloadClientKind = {
  key: 'downloadclient',
  title: 'Download Clients',
  singular: 'Download Client',
  apiBase: '/api/v1/downloadclient',
  rowFields: [
    nameField,
    checkbox(1, 'enabled', 'Enable', 'Enable this download client.'),
    checkbox(2, 'remove_completed_downloads', 'Remove Completed', 'Remove imported downloads from history.'),
  ],
  rowDefaults: { name: '', enabled: true, remove_completed_downloads: true },
  chips: () => [],
};

const newznabSchema = {
  implementation: 'Newznab',
  name: 'Newznab',
  protocol: 'usenet',
  fields: [
    f({ order: 0, name: 'base_url', label: 'URL', help: 'The base URL of the indexer.', required: true }),
    f({ order: 1, name: 'api_key', type: 'password', label: 'API Key', secret: true, required: true }),
    f({
      order: 2,
      name: 'categories',
      type: 'select',
      label: 'Categories',
      help: 'Newznab categories to search.',
      selectOptions: [
        { value: 7030, name: 'Books/Comics (7030)' },
        { value: 7000, name: 'Books (7000)' },
      ],
    }),
    f({ order: 3, name: 'verify_ssl', type: 'checkbox', label: 'Verify SSL', help: "Verify the indexer's TLS certificate." }),
  ],
};

const sabnzbdSchema = {
  implementation: 'Sabnzbd',
  name: 'SABnzbd',
  protocol: 'usenet',
  fields: [
    f({ order: 0, name: 'host', label: 'Host', required: true }),
    f({ order: 1, name: 'port', type: 'number', label: 'Port' }),
    f({ order: 2, name: 'api_key', type: 'password', label: 'API Key', secret: true, required: true }),
    f({ order: 3, name: 'category', label: 'Category', help: 'The SABnzbd category to assign to grabs.' }),
  ],
};

const contain = (children: React.ReactNode) => (
  <div
    style={{
      position: 'relative',
      height: 720,
      transform: 'translateZ(0)',
      overflow: 'hidden',
      borderRadius: 8,
    }}
  >
    {children}
  </div>
);

/** Editing DogNZB: filled form, stored API key held write-only (empty w/ dots). */
export const EditIndexer = () =>
  contain(
    <ProviderModal
      kind={indexerKind}
      schema={newznabSchema}
      provider={{
        id: 1,
        name: 'DogNZB',
        implementation: 'Newznab',
        protocol: 'usenet',
        enabled: true,
        priority: 25,
        enable_rss: true,
        enable_auto: true,
        enable_interactive: true,
        settings: { base_url: 'https://dognzb.cr', categories: [7030], verify_ssl: true },
      }}
      showAdvanced={false}
      onClose={() => {}}
    />,
  );

/** Adding a SABnzbd download client: a fresh form, no Delete button yet. */
export const AddDownloadClient = () =>
  contain(
    <ProviderModal
      kind={downloadClientKind}
      schema={sabnzbdSchema}
      showAdvanced={false}
      onClose={() => {}}
    />,
  );
