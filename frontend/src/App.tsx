import { Routes, Route } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { LibraryIndex } from './screens/library/LibraryIndex';
import { SeriesDetail } from './screens/series/SeriesDetail';
import { AddSeries } from './screens/add/AddSeries';
import { QueueScreen } from './screens/queue/QueueScreen';
import { IndexerSettings } from './routes/settings/IndexerSettings';
import { DownloadClientSettings } from './routes/settings/DownloadClientSettings';
import { MediaManagement } from './screens/settings/MediaManagement';

/**
 * Routing (FRG-UI-001). All change-7 screens are real: library cluster
 * (FRG-UI-003..005), queue (FRG-UI-006), settings on the shared schema-form
 * renderer (FRG-UI-008/009). The interactive-search overlay (FRG-UI-007)
 * mounts from SeriesDetail, not a route.
 */
export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<LibraryIndex />} />
        <Route path="series/:id" element={<SeriesDetail />} />
        <Route path="add" element={<AddSeries />} />
        <Route path="queue" element={<QueueScreen />} />
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
