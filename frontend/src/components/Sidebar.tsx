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

// Placeholder navigation — the real screens (FRG-UI-003..009) mount at these
// routes in change 7 proper; here they are stubs proving the shell/routing.
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
    label: 'Activity',
    items: [{ to: '/queue', label: 'Queue' }],
  },
  {
    label: 'Settings',
    items: [
      { to: '/settings/media-management', label: 'Media Management' },
      { to: '/settings/indexers', label: 'Indexers' },
      { to: '/settings/download-clients', label: 'Download Clients' },
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
