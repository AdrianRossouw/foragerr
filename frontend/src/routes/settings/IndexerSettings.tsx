import { ProviderSettingsPage } from '../../components/settings/ProviderSettingsPage';
import { indexerKind } from '../../components/settings/providerKinds';

/**
 * Settings → Indexers (FRG-UI-008): the generic provider settings screen bound
 * to the indexer kind. Cards, modal, widget map, secrets, and the test button
 * all come from the shared components — nothing indexer-specific but data.
 */
export function IndexerSettings() {
  return <ProviderSettingsPage kind={indexerKind} />;
}
