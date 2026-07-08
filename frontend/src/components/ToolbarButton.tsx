import type { ReactNode } from 'react';
import styles from './ToolbarButton.module.css';

/**
 * Sonarr-style page-toolbar button: icon over a small two-line-capable label
 * (~60px wide), dimmed when disabled, accent icon when toggled active.
 */
export function ToolbarButton({
  icon,
  label,
  onClick,
  disabled = false,
  active = false,
  title,
  testId,
}: {
  icon: ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  /** Toggled state (e.g. current view mode) renders the icon in accent. */
  active?: boolean;
  title?: string;
  /** Optional data-testid for tests that drive a specific toolbar control. */
  testId?: string;
}) {
  return (
    <button
      type="button"
      className={active ? `${styles.button} ${styles.active}` : styles.button}
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active || undefined}
      title={title ?? label}
      data-testid={testId}
    >
      <span className={styles.icon}>{icon}</span>
      <span className={styles.label}>{label}</span>
    </button>
  );
}

/** Thin vertical separator between logical toolbar button groups. */
export function ToolbarSeparator() {
  return <span className={styles.separator} aria-hidden />;
}
