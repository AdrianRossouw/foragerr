import { useRef } from 'react';
import styles from './SegmentedControl.module.css';

/**
 * Shared segmented control (FRG-UI-003, design decision 2) — a compact
 * radio-group of adjacent buttons, one selected. Used for the poster-size
 * S/M/L switch in the Options menu (and available to ch3+ detail toggles).
 * Tokens-only styling; the selected segment reads in the accent-selected tint.
 *
 * Keyboard (radiogroup convention): roving tabindex — only the active segment
 * is in the tab order (tabIndex 0), the rest are -1 — and ArrowLeft/ArrowRight
 * (with Up/Down aliases and Home/End) move the selection, wrapping at the ends,
 * focusing the newly-selected segment. A tabs refactor is recorded as deferred.
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
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const activeIndex = options.findIndex((o) => o.value === value);

  const move = (nextIndex: number) => {
    const opt = options[nextIndex];
    if (!opt) return;
    onChange(opt.value);
    refs.current[nextIndex]?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent, index: number) => {
    const last = options.length - 1;
    switch (e.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        e.preventDefault();
        move(index >= last ? 0 : index + 1);
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        e.preventDefault();
        move(index <= 0 ? last : index - 1);
        break;
      case 'Home':
        e.preventDefault();
        move(0);
        break;
      case 'End':
        e.preventDefault();
        move(last);
        break;
      default:
        break;
    }
  };

  return (
    <span className={styles.group} role="radiogroup" aria-label={ariaLabel}>
      {options.map((opt, index) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            ref={(el) => {
              refs.current[index] = el;
            }}
            type="button"
            role="radio"
            aria-checked={active}
            // Roving tabindex: only the active segment (or the first, if none
            // matches) is tabbable so Tab lands once, then arrows move within.
            tabIndex={active || (activeIndex === -1 && index === 0) ? 0 : -1}
            className={active ? `${styles.segment} ${styles.active}` : styles.segment}
            onClick={() => onChange(opt.value)}
            onKeyDown={(e) => onKeyDown(e, index)}
            data-testid={opt.testId}
          >
            {opt.label}
          </button>
        );
      })}
    </span>
  );
}
