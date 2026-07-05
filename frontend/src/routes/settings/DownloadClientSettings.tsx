import { ProviderSettingsPage } from '../../components/settings/ProviderSettingsPage';
import { downloadClientKind } from '../../components/settings/providerKinds';

/**
 * Settings → Download Clients (FRG-UI-009): the SAME generic renderer and
 * settings screen as indexers, bound to the download-client kind config.
 * ZERO download-client-specific form code exists — this file must stay a pure
 * binding; the renderer-reuse audit test fails the build if form-rendering
 * JSX ever appears in this screen's module graph outside the shared renderer.
 */
export function DownloadClientSettings() {
  return <ProviderSettingsPage kind={downloadClientKind} />;
}
