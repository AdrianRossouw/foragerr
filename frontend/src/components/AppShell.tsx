import { Outlet, useNavigate } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { HeaderQuickSearch } from './HeaderQuickSearch';
import { GlobalBanner } from './GlobalBanner';
import { WebSocketBridge } from '../ws/WebSocketBridge';
import { useHasExpiredSource } from '../api/sourceHooks';
import type { SocketFactory } from '../ws/socket';
import styles from './AppShell.module.css';

/**
 * Application shell (FRG-UI-023): the fixed three-part frame every screen
 * renders inside — a 212px sidebar (nav + counts + system section + status
 * footer), a 60px global header (the relocated quick-search FRG-UI-019 on the
 * left, health/system icon buttons on the right), and the main column whose
 * per-screen toolbar + content region is the only scrolling area. Mounts the
 * single WebSocketBridge so cache invalidation/patch and connection state are
 * wired app-wide; `socketFactory` is injectable so tests can drive a fake
 * socket.
 */
export function AppShell({ socketFactory }: { socketFactory?: SocketFactory }) {
  const navigate = useNavigate();
  // A store-session expiry tints the header health icon amber and pulses it
  // (design handoff §Connection lifecycle) — the same signal that raises the
  // global banner and flips the sidebar footer.
  const expired = useHasExpiredSource();
  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href="#main-content">
        Skip to content
      </a>
      <WebSocketBridge socketFactory={socketFactory} />
      <Sidebar />
      <div className={styles.main}>
        <GlobalBanner />
        <header className={styles.header}>
          <div className={styles.headerSearch}>
            <HeaderQuickSearch />
          </div>
          <div className={styles.headerSpacer} />
          <div className={styles.headerActions}>
            <button
              type="button"
              className={
                expired
                  ? `${styles.iconButton} ${styles.iconButtonWarn}`
                  : styles.iconButton
              }
              aria-label="System health"
              title={expired ? 'A store session needs attention' : 'Health'}
              data-testid="header-health"
              data-expired={expired ? 'true' : 'false'}
              onClick={() => navigate('/system/health')}
            >
              <i className="fa-solid fa-heart-pulse" aria-hidden />
            </button>
            <button
              type="button"
              className={styles.iconButton}
              aria-label="System status"
              title="System"
              data-testid="header-system"
              onClick={() => navigate('/system/status')}
            >
              <i className="fa-solid fa-server" aria-hidden />
            </button>
          </div>
        </header>
        <div className={styles.outlet} id="main-content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
