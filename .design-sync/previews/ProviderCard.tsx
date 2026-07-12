import { ProviderCard } from 'foragerr-frontend';

/*
 * ProviderCard (FRG-UI-008/009) — one configured provider row in the settings
 * card grid: name, capability/status chips, and an enable switch. Kind configs
 * are pure data (inlined here to match providerKinds.ts, since they are not part
 * of the package's public exports).
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

const downloadClientKind = {
  key: 'downloadclient',
  title: 'Download Clients',
  singular: 'Download Client',
  apiBase: '/api/v1/downloadclient',
  rowFields: [],
  rowDefaults: {},
  chips: (p: Record<string, unknown>): Chip[] =>
    p.enabled
      ? [{ label: 'Enabled', tone: 'success' }]
      : [{ label: 'Disabled', tone: 'danger' }],
};

const frame = (children: React.ReactNode) => (
  <div style={{ maxWidth: 320 }}>{children}</div>
);

/** An enabled Newznab indexer with all three search capabilities on. */
export const EnabledIndexer = () =>
  frame(
    <ProviderCard
      kind={indexerKind}
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
        settings: {},
      }}
      onEdit={() => {}}
      onToggle={() => {}}
    />,
  );

/** A disabled indexer collapses to the single danger "Disabled" chip. */
export const DisabledIndexer = () =>
  frame(
    <ProviderCard
      kind={indexerKind}
      provider={{
        id: 2,
        name: 'NZB.su',
        implementation: 'Newznab',
        protocol: 'usenet',
        enabled: false,
        priority: 25,
        enable_rss: true,
        enable_auto: false,
        enable_interactive: true,
        settings: {},
      }}
      onEdit={() => {}}
      onToggle={() => {}}
    />,
  );

/** A download client uses the other kind config: a single Enabled/Disabled chip. */
export const DownloadClientCard = () =>
  frame(
    <ProviderCard
      kind={downloadClientKind}
      provider={{
        id: 3,
        name: 'SABnzbd',
        implementation: 'Sabnzbd',
        protocol: 'usenet',
        enabled: true,
        priority: 1,
        remove_completed_downloads: true,
        settings: {},
      }}
      onEdit={() => {}}
      onToggle={() => {}}
    />,
  );
