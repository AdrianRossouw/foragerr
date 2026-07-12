import { ProviderSettingsPage, PreviewData } from 'foragerr-frontend';

/*
 * ProviderSettingsPage (FRG-UI-008/009) — the whole generic settings screen:
 * toolbar (Show Advanced / dirty-save), underlined heading, and the P11 card
 * grid of configured providers plus the `+` add card. Seeded via PreviewData
 * with realistic Newznab indexers. Two response keys are needed because both
 * the list path (/api/v1/indexer) and the schema path (/api/v1/indexer/schema)
 * contain "indexer" — the more specific key is listed first so it wins.
 */

type Chip = { label: string; tone: 'success' | 'danger' | 'warning' | 'muted' };

const indexerKind = {
  key: 'indexer',
  title: 'Indexers',
  singular: 'Indexer',
  apiBase: '/api/v1/indexer',
  rowFields: [],
  rowDefaults: {},
  chips: (p: Record<string, unknown>): Chip[] => {
    if (!p.enabled) return [{ label: 'Disabled', tone: 'danger' }];
    const chips: Chip[] = [];
    if (p.enable_rss) chips.push({ label: 'RSS', tone: 'success' });
    if (p.enable_auto) chips.push({ label: 'Automatic Search', tone: 'success' });
    if (p.enable_interactive)
      chips.push({ label: 'Interactive Search', tone: 'success' });
    return chips;
  },
};

const indexers = [
  {
    id: 1,
    name: 'DogNZB',
    implementation: 'Newznab',
    protocol: 'usenet',
    enabled: true,
    priority: 25,
    enable_rss: true,
    enable_auto: true,
    enable_interactive: true,
    settings: {},
  },
  {
    id: 2,
    name: 'NZB.su',
    implementation: 'Newznab',
    protocol: 'usenet',
    enabled: true,
    priority: 25,
    enable_rss: true,
    enable_auto: false,
    enable_interactive: true,
    settings: {},
  },
  {
    id: 3,
    name: 'NZBgeek',
    implementation: 'Newznab',
    protocol: 'usenet',
    enabled: false,
    priority: 30,
    enable_rss: true,
    enable_auto: true,
    enable_interactive: true,
    settings: {},
  },
];

const schemas = [
  {
    implementation: 'Newznab',
    name: 'Newznab',
    protocol: 'usenet',
    fields: [],
  },
];

/** The Indexers settings page with three seeded providers and the add card. */
export const IndexerSettings = () => (
  <PreviewData
    responses={{
      'indexer/schema': schemas,
      indexer: indexers,
    }}
  >
    <ProviderSettingsPage kind={indexerKind} />
  </PreviewData>
);
