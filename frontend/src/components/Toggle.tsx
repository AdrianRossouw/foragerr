import styles from './Toggle.module.css';

/**
 * Sliding switch (FRG-UI-029): the account bar's "Auto-sync new purchases"
 * control and the manage view's non-comic reveal. A `role="switch"` button with
 * a knob; all color comes from tokens (accent-on when checked). Distinct from
 * the bookmark `MonitorToggle` — this is the on/off track+knob idiom.
 */
export function Toggle({
  checked,
  onChange,
  label,
  disabled = false,
  title,
  testId,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  /** Accessible name for the switch. */
  label: string;
  disabled?: boolean;
  title?: string;
  testId?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={title}
      disabled={disabled}
      data-testid={testId}
      className={`${styles.track} ${checked ? styles.on : ''}`}
      onClick={() => onChange(!checked)}
    >
      <span className={styles.knob} aria-hidden />
    </button>
  );
}
