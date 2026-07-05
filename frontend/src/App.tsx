import { Routes, Route } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { LibraryIndex } from './screens/library/LibraryIndex';
import { SeriesDetail } from './screens/series/SeriesDetail';
import { AddSeries } from './screens/add/AddSeries';
import { QueuePlaceholder, SettingsPlaceholder } from './routes/placeholders';

/**
 * Routing skeleton (FRG-UI-001). Library-cluster screens (FRG-UI-003..005)
 * are real; remaining placeholders are replaced by their own change-7 tasks.
 */
export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<LibraryIndex />} />
        <Route path="series/:id" element={<SeriesDetail />} />
        <Route path="add" element={<AddSeries />} />
        <Route path="queue" element={<QueuePlaceholder />} />
        <Route
          path="settings/indexers"
          element={<SettingsPlaceholder area="Indexers" />}
        />
        <Route
          path="settings/download-clients"
          element={<SettingsPlaceholder area="Download Clients" />}
        />
      </Route>
    </Routes>
  );
}
