import { Routes, Route } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { LoginScreen } from './screens/auth/LoginScreen';
import { LibraryIndex } from './screens/library/LibraryIndex';
import { SeriesDetailRoute } from './screens/series/SeriesDetail';
import { AddSeries } from './screens/add/AddSeries';
import { LibraryImport } from './screens/library-import/LibraryImport';
import { QueueScreen } from './screens/queue/QueueScreen';
import { HistoryScreen } from './screens/history/HistoryScreen';
import { BlocklistScreen } from './screens/blocklist/BlocklistScreen';
import { WantedScreen } from './screens/wanted/WantedScreen';
import { SourcesScreen } from './screens/sources/SourcesScreen';
import { CalendarScreen } from './screens/calendar/CalendarScreen';
import { CreatorsScreen } from './screens/creators/CreatorsScreen';
import { CreatorProfileRoute } from './screens/creators/CreatorProfile';
import { IndexerSettings } from './routes/settings/IndexerSettings';
import { DownloadClientSettings } from './routes/settings/DownloadClientSettings';
import { MediaManagement } from './screens/settings/MediaManagement';
import { General } from './screens/settings/General';
import { Security } from './screens/settings/Security';
import { StatusScreen } from './screens/system/StatusScreen';
import { HealthScreen } from './screens/system/HealthScreen';
import { TasksScreen } from './screens/system/TasksScreen';
import { LogsScreen } from './screens/system/LogsScreen';
import { NotFound } from './screens/NotFound';

/**
 * Routing (FRG-UI-001). All change-7 screens are real: library cluster
 * (FRG-UI-003..005), queue (FRG-UI-006), settings on the shared schema-form
 * renderer (FRG-UI-008/009). The interactive-search overlay (FRG-UI-007)
 * mounts from SeriesDetail/Wanted, not a route. m2-daily-surfaces adds the
 * daily review screens: wanted (FRG-UI-011), history (FRG-UI-010), and
 * blocklist (FRG-UI-017). m2-ops-health-backups adds the System area
 * (FRG-UI-016): status, health, and tasks. m4-logs-viewer adds System — Logs
 * (FRG-UI-024). m8-auth-core adds /login, sitting OUTSIDE the `AppShell`
 * route (no sidebar/header for an unauthenticated visitor) — `AuthGate`
 * (mounted around this whole component in main.tsx) decides which of the two
 * subtrees is actually reachable at any moment. m8-keys-opds adds
 * settings/security (FRG-AUTH-004/005/007): the credential-lifecycle
 * Settings page (password/OPDS-password/API-key/logout-all), inside
 * `AppShell` like every other settings screen.
 */
export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginScreen />} />
      <Route element={<AppShell />}>
        <Route index element={<LibraryIndex />} />
        <Route path="series/:id" element={<SeriesDetailRoute />} />
        <Route path="calendar" element={<CalendarScreen />} />
        <Route path="creators" element={<CreatorsScreen />} />
        <Route path="creators/:id" element={<CreatorProfileRoute />} />
        <Route path="add" element={<AddSeries />} />
        <Route path="library-import" element={<LibraryImport />} />
        <Route path="wanted" element={<WantedScreen />} />
        <Route path="sources" element={<SourcesScreen />} />
        <Route path="queue" element={<QueueScreen />} />
        <Route path="history" element={<HistoryScreen />} />
        <Route path="blocklist" element={<BlocklistScreen />} />
        <Route path="settings/general" element={<General />} />
        <Route path="settings/indexers" element={<IndexerSettings />} />
        <Route
          path="settings/download-clients"
          element={<DownloadClientSettings />}
        />
        <Route
          path="settings/media-management"
          element={<MediaManagement />}
        />
        <Route path="settings/security" element={<Security />} />
        <Route path="system/status" element={<StatusScreen />} />
        <Route path="system/health" element={<HealthScreen />} />
        <Route path="system/tasks" element={<TasksScreen />} />
        <Route path="system/logs" element={<LogsScreen />} />
        {/* Catch-all (FRG-UI-036): any undefined path renders the not-found
            screen inside the shell, never a blank page. */}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
