import { Link, NavLink } from 'react-router-dom';
import { useConnectionStore, type ConnectionStatus } from '../ws/connectionStore';
import {
  useSeriesIndex,
  useQueueCount,
  useHealthWarnings,
  useSystemStatus,
} from '../api/hooks';
import { useSources, useSourcesNewCount } from '../api/sourceHooks';
import { LogoMarkIcon } from './icons';
import styles from './AppShell.module.css';

/**
 * Sidebar (FRG-UI-023): logo lockup, a nav list of the SHIPPED screens with
 * live count badges (Comics = library series count, Queue = tracked-download
 * count, Wanted = series-with-missing-issues in warn style), grouped operator
 * sections, and a footer status row (health pulse + running version). Calendar
 * ships in m4-pull-experience (FRG-UI-018); Creators enters the nav here in
 * m5-creators-screens (FRG-UI-027), the change that ships its screen (mirrors
 * the README shipped-claims rule). All counts read
 * existing React Query caches kept live by the WebSocketBridge (no new
 * endpoints, no polling timers of their own).
 */

type BadgeKind = 'series' | 'queue' | 'wanted';

interface NavItem {
  to: string;
  label: string;
  /** Font Awesome 6 Free (self-hosted) glyph class. */
  icon: string;
  end?: boolean;
  badge?: BadgeKind | 'sources';
}

interface NavGroup {
  /** Uppercased section label, or null for the top (unlabelled) group. */
  label: string | null;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: null,
    items: [
      { to: '/', label: 'Comics', icon: 'fa-book', end: true, badge: 'series' },
      { to: '/creators', label: 'Creators', icon: 'fa-user-pen' },
      { to: '/calendar', label: 'Calendar', icon: 'fa-calendar-days' },
      { to: '/add', label: 'Add New', icon: 'fa-plus' },
      { to: '/library-import', label: 'Library Import', icon: 'fa-folder-tree' },
      {
        to: '/wanted',
        label: 'Wanted',
        icon: 'fa-triangle-exclamation',
        badge: 'wanted',
      },
      {
        to: '/sources',
        label: 'Sources',
        icon: 'fa-store',
        badge: 'sources',
      },
    ],
  },
  {
    label: 'Activity',
    items: [
      { to: '/queue', label: 'Queue', icon: 'fa-download', badge: 'queue' },
      { to: '/history', label: 'History', icon: 'fa-clock-rotate-left' },
      { to: '/blocklist', label: 'Blocklist', icon: 'fa-ban' },
    ],
  },
  {
    label: 'Settings',
    items: [
      { to: '/settings/general', label: 'General', icon: 'fa-key' },
      {
        to: '/settings/media-management',
        label: 'Media Management',
        icon: 'fa-folder',
      },
      { to: '/settings/indexers', label: 'Indexers', icon: 'fa-magnifying-glass' },
      {
        to: '/settings/download-clients',
        label: 'Download Clients',
        icon: 'fa-cloud-arrow-down',
      },
      { to: '/settings/security', label: 'Security', icon: 'fa-shield-halved' },
    ],
  },
  {
    label: 'System',
    items: [
      { to: '/system/status', label: 'Status', icon: 'fa-circle-info' },
      { to: '/system/health', label: 'Health', icon: 'fa-heart-pulse' },
      { to: '/system/tasks', label: 'Tasks', icon: 'fa-list-check' },
      { to: '/system/logs', label: 'Logs', icon: 'fa-file-lines' },
    ],
  },
];

const CONNECTION_LABEL: Record<ConnectionStatus, string> = {
  connecting: 'Connecting…',
  connected: 'Connected',
  disconnected: 'Disconnected',
};

const CONNECTION_CLASS: Record<ConnectionStatus, string> = {
  connecting: styles.connConnecting,
  connected: styles.connConnected,
  disconnected: styles.connDisconnected,
};

function NavBadge({ kind }: { kind: BadgeKind }) {
  const series = useSeriesIndex();
  const queueCount = useQueueCount();

  let value: number | undefined;
  let warn = false;
  if (kind === 'series') {
    value = series.data?.length;
  } else if (kind === 'queue') {
    value = queueCount.data;
  } else {
    value = series.data?.filter((s) => s.statistics.missing_count > 0).length;
    warn = true;
  }

  // A badge only appears once its count is loaded and non-zero — an empty
  // library / idle queue shows a clean label, matching the design.
  if (value === undefined || value <= 0) return null;
  return (
    <span
      className={warn ? `${styles.navBadge} ${styles.navBadgeWarn}` : styles.navBadge}
      data-testid={`nav-badge-${kind}`}
    >
      {value}
    </span>
  );
}

/**
 * Sources nav badge (FRG-UI-029): an amber `!` when any connected store's
 * session has expired (the more serious signal, always wins), else the count of
 * unreviewed `new` items across connected sources. Both use the warn (amber)
 * style. No source configured / nothing pending / all clean → no badge.
 */
function SourcesNavBadge() {
  const sources = useSources();
  const connectedIds = (sources.data ?? [])
    .filter((s) => s.connection_state === 'connected')
    .map((s) => s.id);
  const expired = (sources.data ?? []).some(
    (s) => s.connection_state === 'expired',
  );
  const newCount = useSourcesNewCount(connectedIds);

  if (expired) {
    return (
      <span
        className={`${styles.navBadge} ${styles.navBadgeWarn}`}
        data-testid="nav-badge-sources"
        aria-label="A store session needs attention"
      >
        !
      </span>
    );
  }
  const value = newCount.data;
  if (value === undefined || value <= 0) return null;
  return (
    <span
      className={`${styles.navBadge} ${styles.navBadgeWarn}`}
      data-testid="nav-badge-sources"
    >
      {value}
    </span>
  );
}

export function Sidebar() {
  const connection = useConnectionStore((s) => s.status);
  const health = useHealthWarnings();
  const status = useSystemStatus();
  const sources = useSources();

  // A store-session expiry surfaces in the footer immediately off the
  // authoritative sources cache (design handoff: "Humble sync needs attention"),
  // rather than waiting on the 15s health poll that also reports it.
  const sourceExpired = (sources.data ?? []).some(
    (s) => s.connection_state === 'expired',
  );

  // Health pulse: healthy until the warnings list reports at least one active
  // warning. While loading (undefined) the sidebar reads as healthy rather than
  // flashing an alarm state.
  const warningCount = health.data?.length ?? 0;
  const healthy = warningCount === 0 && !sourceExpired;
  const healthDotClass = !healthy
    ? styles.statusWarn
    : connection === 'disconnected'
      ? styles.statusDisconnected
      : styles.statusHealthy;
  // Visible footer text must not claim "all healthy" while the socket is down —
  // the red connection dot and the words would contradict each other. Health
  // warnings still take precedence (they are the more serious signal); otherwise
  // a dropped/reconnecting socket surfaces as "reconnecting…", and only a
  // connected, warning-free app reads "all healthy".
  const healthLabel =
    sourceExpired && warningCount === 0
      ? 'sync needs attention'
      : !healthy
        ? `${warningCount} warning${warningCount === 1 ? '' : 's'}`
        : connection !== 'connected'
          ? 'reconnecting…'
          : 'all healthy';
  const version = status.data?.version;

  return (
    <aside className={styles.sidebar}>
      {/* The lockup doubles as the way home (owner request 2026-07-10). */}
      <Link to="/" className={styles.brand} aria-label="Foragerr — home">
        <span className={styles.brandTile} aria-hidden>
          <LogoMarkIcon size={21} />
        </span>
        <span className={styles.brandWord}>
          Forage<span className={styles.brandWordAccent}>rr</span>
        </span>
      </Link>
      <nav className={styles.nav} aria-label="Primary">
        {NAV_GROUPS.map((group, index) => (
          <div key={group.label ?? `group-${index}`}>
            {group.label && (
              <div className={styles.navGroupLabel}>{group.label}</div>
            )}
            {group.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  isActive
                    ? `${styles.navLink} ${styles.navLinkActive}`
                    : styles.navLink
                }
              >
                <span className={styles.navIcon} aria-hidden>
                  <i className={`fa-solid ${item.icon}`} />
                </span>
                <span className={styles.navLabel}>{item.label}</span>
                {item.badge === 'sources' ? (
                  <SourcesNavBadge />
                ) : (
                  item.badge && <NavBadge kind={item.badge} />
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <div
        className={styles.footer}
        data-testid="sidebar-status"
        role="status"
        aria-live="polite"
      >
        <span className={`${styles.statusDot} ${healthDotClass}`} aria-hidden />
        <span className={styles.footerText}>
          Foragerr{version ? ` ${version}` : ''} — {healthLabel}
        </span>
        <span
          className={`${styles.connDot} ${CONNECTION_CLASS[connection]}`}
          data-testid="connection-status"
          data-status={connection}
          aria-label={CONNECTION_LABEL[connection]}
          title={CONNECTION_LABEL[connection]}
        />
      </div>
    </aside>
  );
}
