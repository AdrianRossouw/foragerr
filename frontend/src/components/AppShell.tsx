import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { HeaderQuickSearch } from './HeaderQuickSearch';
import { WebSocketBridge } from '../ws/WebSocketBridge';
import type { SocketFactory } from '../ws/socket';
import styles from './AppShell.module.css';

/**
 * App shell (FRG-UI-001): dark left sidebar + global header + per-page toolbar
 * + main content outlet, all styled from the design tokens. The header hosts
 * the global quick-search (FRG-UI-019), present on every route. Mounts the
 * single WebSocketBridge so cache invalidation/patch and connection state are
 * wired app-wide. `socketFactory` is injectable so tests can drive a fake
 * socket.
 */
export function AppShell({ socketFactory }: { socketFactory?: SocketFactory }) {
  return (
    <div className={styles.shell}>
      <WebSocketBridge socketFactory={socketFactory} />
      <Sidebar />
      <div className={styles.main}>
        <header className={styles.header}>
          <HeaderQuickSearch />
        </header>
        <Outlet />
      </div>
    </div>
  );
}
