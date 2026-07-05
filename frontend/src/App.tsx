import { Routes, Route } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import {
  LibraryIndexPlaceholder,
  SeriesDetailPlaceholder,
  AddSeriesPlaceholder,
} from './routes/placeholders';
import { QueueScreen } from './screens/queue/QueueScreen';
import { IndexerSettings } from './routes/settings/IndexerSettings';
import { DownloadClientSettings } from './routes/settings/DownloadClientSettings';

/**
 * Routing skeleton (FRG-UI-001). Placeholder route components mount inside the
 * shell; real screens replace them in change 7 proper.
 */
export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<LibraryIndexPlaceholder />} />
        <Route path="series/:id" element={<SeriesDetailPlaceholder />} />
        <Route path="add" element={<AddSeriesPlaceholder />} />
        <Route path="queue" element={<QueueScreen />} />
        <Route path="settings/indexers" element={<IndexerSettings />} />
        <Route
          path="settings/download-clients"
          element={<DownloadClientSettings />}
        />
      </Route>
    </Routes>
  );
}
