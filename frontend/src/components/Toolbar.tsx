import type { ReactNode } from 'react';
import styles from './AppShell.module.css';

/**
 * Top toolbar region of the Sonarr-shaped shell. Pages inject their own actions;
 * here it renders the current route title as a placeholder.
 */
export function Toolbar({ title, actions }: { title: string; actions?: ReactNode }) {
  return (
    <div className={styles.toolbar}>
      <strong>{title}</strong>
      <span style={{ flex: 1 }} />
      {actions}
    </div>
  );
}
