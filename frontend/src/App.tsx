import { Routes, Route } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { LibraryIndex } from './screens/library/LibraryIndex';
import { SeriesDetail } from './screens/series/SeriesDetail';
import { AddSeries } from './screens/add/AddSeries';
import { LibraryImport } from './screens/library-import/LibraryImport';
import { QueueScreen } from './screens/queue/QueueScreen';
import { HistoryScreen } from './screens/history/HistoryScreen';
import { BlocklistScreen } from './screens/blocklist/BlocklistScreen';
import { WantedScreen } from './screens/wanted/WantedScreen';
import { IndexerSettings } from './routes/settings/IndexerSettings';
import { DownloadClientSettings } from './routes/settings/DownloadClientSettings';
import { MediaManagement } from './screens/settings/MediaManagement';

/**
 * Routing (FRG-UI-001). All change-7 screens are real: library cluster
 * (FRG-UI-003..005), queue (FRG-UI-006), settings on the shared schema-form
 * renderer (FRG-UI-008/009). The interactive-search overlay (FRG-UI-007)
 * mounts from SeriesDetail/Wanted, not a route. m2-daily-surfaces adds the
 * daily review screens: wanted (FRG-UI-011), history (FRG-UI-010), and
 * blocklist (FRG-UI-017).
 */
export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<LibraryIndex />} />
        <Route path="series/:id" element={<SeriesDetail />} />
        <Route path="add" element={<AddSeries />} />
        <Route path="library-import" element={<LibraryImport />} />
        <Route path="wanted" element={<WantedScreen />} />
        <Route path="queue" element={<QueueScreen />} />
        <Route path="history" element={<HistoryScreen />} />
        <Route path="blocklist" element={<BlocklistScreen />} />
        <Route path="settings/indexers" element={<IndexerSettings />} />
        <Route
          path="settings/download-clients"
          element={<DownloadClientSettings />}
        />
        <Route
          path="settings/media-management"
          element={<MediaManagement />}
        />
      </Route>
    </Routes>
  );
}
