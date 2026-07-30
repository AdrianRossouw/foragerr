import { useCallback, useEffect, useRef, useState } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { HeaderQuickSearch } from './HeaderQuickSearch';
import { GlobalBanner } from './GlobalBanner';
import { WebSocketBridge } from '../ws/WebSocketBridge';
import { useHasExpiredSource } from '../api/sourceHooks';
import { useCompactViewport } from '../theme/useCompactViewport';
import { LogoutButton } from './LogoutButton';
import type { SocketFactory } from '../ws/socket';
import styles from './AppShell.module.css';

/**
 * Application shell (FRG-UI-023): the fixed three-part frame every screen
 * renders inside — a 212px sidebar (nav + counts + system section + status
 * footer), a 60px global header (the relocated quick-search FRG-UI-019 on the
 * left, health/system/logout icon buttons on the right), and the main column
 * whose per-screen toolbar + content region is the only scrolling area.
 * Mounts the single WebSocketBridge so cache invalidation/patch and
 * connection state are wired app-wide; `socketFactory` is injectable so tests
 * can drive a fake socket. Only ever mounted inside `AuthGate`'s
 * authenticated tree (m8-auth-core) — logging out or a 401 mid-session
 * unmounts it, which is what closes the socket.
 *
 * Below the compact crossover (FRG-UI-049, theme/layout.ts) the sidebar holds no
 * column at all: it becomes an off-canvas drawer behind a header toggle, and the
 * content region spans the viewport. The drawer is CONDITIONALLY RENDERED rather
 * than translated off-screen — a hidden-but-present nav would stay in keyboard
 * order and in the accessibility tree — and the toggle exists only in compact
 * mode, which is why the crossover is evaluated in JS and not in a media query.
 */
export function AppShell({ socketFactory }: { socketFactory?: SocketFactory }) {
  const navigate = useNavigate();
  // A store-session expiry tints the header health icon amber and pulses it
  // (design handoff §Connection lifecycle) — the same signal that raises the
  // global banner and flips the sidebar footer.
  const expired = useHasExpiredSource();
  const compact = useCompactViewport();
  const [navOpen, setNavOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLDivElement>(null);

  // Returning focus is only correct for a deliberate dismissal; widening the
  // viewport past the crossover unmounts the drawer without a focus move.
  const closeNav = useCallback(() => {
    setNavOpen(false);
    toggleRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!compact) setNavOpen(false);
  }, [compact]);

  useEffect(() => {
    if (!navOpen) return;
    // Focus enters the drawer on open so a keyboard operator is not left behind
    // the toggle with the nav they just asked for out of reach.
    drawerRef.current
      ?.querySelector<HTMLElement>('a[href], button:not([disabled])')
      ?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeNav();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [navOpen, closeNav]);

  return (
    <div className={styles.shell} data-compact={compact ? 'true' : 'false'}>
      <a className={styles.skipLink} href="#main-content">
        Skip to content
      </a>
      <WebSocketBridge socketFactory={socketFactory} />
      {!compact && <Sidebar />}
      {compact && navOpen && (
        <>
          <div
            className={styles.navBackdrop}
            data-testid="nav-backdrop"
            onClick={closeNav}
            aria-hidden
          />
          <div
            className={styles.navDrawer}
            id="nav-drawer"
            ref={drawerRef}
            data-testid="nav-drawer"
          >
            <Sidebar onNavigate={closeNav} />
          </div>
        </>
      )}
      <div className={styles.main}>
        <GlobalBanner />
        <header className={styles.header}>
          {compact && (
            <button
              type="button"
              ref={toggleRef}
              className={styles.iconButton}
              aria-label={navOpen ? 'Close navigation' : 'Open navigation'}
              aria-expanded={navOpen}
              aria-controls="nav-drawer"
              title="Navigation"
              data-testid="nav-toggle"
              onClick={() => (navOpen ? closeNav() : setNavOpen(true))}
            >
              <i className="fa-solid fa-bars" aria-hidden />
            </button>
          )}
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
            <LogoutButton />
          </div>
        </header>
        <div className={styles.outlet} id="main-content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
