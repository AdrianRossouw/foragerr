import { NavLink } from 'react-router-dom';
import { useConnectionStore, type ConnectionStatus } from '../ws/connectionStore';
import styles from './AppShell.module.css';

interface NavItem {
  to: string;
  label: string;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

// Sonarr-shaped navigation over the real screens: the library cluster
// (FRG-UI-003..005, FRG-UI-015), Wanted as its own group (FRG-UI-011), the
// Activity group (queue FRG-UI-006, history FRG-UI-010, blocklist FRG-UI-017),
// and settings (FRG-UI-008/009/012).
const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Library',
    items: [
      { to: '/', label: 'Series' },
      { to: '/add', label: 'Add New' },
      { to: '/library-import', label: 'Library Import' },
    ],
  },
  {
    label: 'Wanted',
    items: [{ to: '/wanted', label: 'Missing' }],
  },
  {
    label: 'Activity',
    items: [
      { to: '/queue', label: 'Queue' },
      { to: '/history', label: 'History' },
      { to: '/blocklist', label: 'Blocklist' },
    ],
  },
  {
    label: 'Settings',
    items: [
      { to: '/settings/media-management', label: 'Media Management' },
      { to: '/settings/indexers', label: 'Indexers' },
      { to: '/settings/download-clients', label: 'Download Clients' },
    ],
  },
  // System (FRG-UI-016, m2-ops-health-backups): the operator's view of the
  // running instance — status/paths/runtime, health warnings + per-component
  // state, and the scheduled-task list with force-run/"Back up now".
  {
    label: 'System',
    items: [
      { to: '/system/status', label: 'Status' },
      { to: '/system/health', label: 'Health' },
      { to: '/system/tasks', label: 'Tasks' },
    ],
  },
];

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  connecting: 'Connecting…',
  connected: 'Connected',
  disconnected: 'Disconnected',
};

const STATUS_CLASS: Record<ConnectionStatus, string> = {
  connecting: styles.statusConnecting,
  connected: styles.statusConnected,
  disconnected: styles.statusDisconnected,
};

export function Sidebar() {
  const status = useConnectionStore((s) => s.status);

  return (
    <aside className={styles.sidebar}>
      <div className={styles.brand}>
        <span className={styles.brandMark} aria-hidden>
          ▲
        </span>
        <span>foragerr</span>
      </div>
      <nav className={styles.nav}>
        {NAV_GROUPS.map((group) => (
          <div key={group.label}>
            <div className={styles.navGroupLabel}>{group.label}</div>
            {group.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  isActive
                    ? `${styles.navLink} ${styles.navLinkActive}`
                    : styles.navLink
                }
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <div className={styles.footer} data-testid="connection-status">
        <span
          className={`${styles.statusDot} ${STATUS_CLASS[status]}`}
          aria-hidden
        />
        <span>{STATUS_LABEL[status]}</span>
      </div>
    </aside>
  );
}
