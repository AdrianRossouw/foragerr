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
 *
 * The open drawer is modal for every input mode, not just the mouse: the
 * backdrop already intercepts every click over the frame, so the rest of the
 * frame is marked `inert` while it is open. That is what makes
 * `role="dialog" aria-modal="true"` true rather than a claim — without the
 * containment, assistive technology would hide the outside world while Tab still
 * walked into it, behind an opaque backdrop.
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
  // viewport past the crossover unmounts the drawer without a focus move — so
  // the intent is recorded here and consumed by the effect below rather than
  // acted on inline. At this point the state change has not been committed and
  // the toggle is still inside the `inert` subtree, where a `focus()` call is
  // ignored by the browser.
  const restoreFocus = useRef(false);
  const closeNav = useCallback(() => {
    restoreFocus.current = true;
    setNavOpen(false);
  }, []);

  const shellRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (navOpen || !restoreFocus.current) return;
    // Post-commit: the drawer is gone and the frame is no longer inert, so the
    // toggle can take focus. Only a dismissal sets the flag, which is what keeps
    // this from fighting the widen effect's move into the persistent nav.
    restoreFocus.current = false;
    toggleRef.current?.focus();
  }, [navOpen]);

  useEffect(() => {
    if (compact || !navOpen) return;
    // Widening past the crossover unmounts the drawer without a dismissal, so
    // focus that was inside it would otherwise fall to the document body and
    // restart the tab order. The nav it held is now the persistent column.
    shellRef.current?.querySelector<HTMLElement>('nav a[href]')?.focus();
    setNavOpen(false);
  }, [compact, navOpen]);

  useEffect(() => {
    if (!navOpen) return;
    // Focus enters the drawer on open so a keyboard operator is not left behind
    // the toggle with the nav they just asked for out of reach — at the first
    // NAV item, not the brand lockup that precedes it (which is a link home, so
    // the first Enter would leave the screen).
    drawerRef.current
      ?.querySelector<HTMLElement>('nav a[href], nav button:not([disabled])')
      ?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeNav();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [navOpen, closeNav]);

  // Everything outside the drawer, while it is open: `inert` is native focus
  // containment plus accessibility-tree exclusion in one attribute, so no
  // keydown trap is needed and nothing behind the backdrop is reachable. The
  // condition must be the drawer's OWN render condition: keyed off `navOpen`
  // alone, widening past the crossover paints a frame in which the whole app is
  // inert and no drawer exists to hold focus.
  const outsideDrawer = compact && navOpen ? ('' as const) : undefined;

  return (
    <div
      className={styles.shell}
      data-compact={compact ? 'true' : 'false'}
      ref={shellRef}
    >
      <a className={styles.skipLink} href="#main-content" inert={outsideDrawer}>
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
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            data-testid="nav-drawer"
          >
            <Sidebar onNavigate={closeNav} />
          </div>
        </>
      )}
      <div className={styles.main} inert={outsideDrawer}>
        <GlobalBanner />
        <header className={styles.header}>
          {compact && (
            // An OPEN control only: while the drawer is open this button sits in
            // the inert subtree behind the backdrop, so it cannot be reached by
            // pointer or by keyboard. A "Close navigation" name and a dismissing
            // branch would both describe something no operator can do — the
            // drawer is dismissed by Escape or by the backdrop. `aria-expanded`
            // still carries the state the toggle is returned to.
            <button
              type="button"
              ref={toggleRef}
              className={styles.iconButton}
              aria-label="Open navigation"
              aria-expanded={navOpen}
              aria-controls="nav-drawer"
              title="Navigation"
              data-testid="nav-toggle"
              onClick={() => setNavOpen(true)}
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
