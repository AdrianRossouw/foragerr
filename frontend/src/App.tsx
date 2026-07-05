import { Routes, Route } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import {
  LibraryIndexPlaceholder,
  SeriesDetailPlaceholder,
  AddSeriesPlaceholder,
  QueuePlaceholder,
  SettingsPlaceholder,
} from './routes/placeholders';

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
