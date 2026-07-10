import styles from './SegmentedControl.module.css';

/**
 * Shared segmented control (FRG-UI-003, design decision 2) — a compact
 * radio-group of adjacent buttons, one selected. Used for the poster-size
 * S/M/L switch in the Options menu (and available to ch3+ detail toggles).
 * Tokens-only styling; the selected segment reads in the accent-selected tint.
 */
export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  testId?: string;
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: readonly SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
}) {
  return (
    <span className={styles.group} role="radiogroup" aria-label={ariaLabel}>
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            className={active ? `${styles.segment} ${styles.active}` : styles.segment}
            onClick={() => onChange(opt.value)}
            data-testid={opt.testId}
          >
            {opt.label}
          </button>
        );
      })}
    </span>
  );
}
