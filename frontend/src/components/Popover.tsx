import {
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import styles from './Popover.module.css';

export interface PopoverProps {
  /** Trigger content — typically a status/decision chip. */
  trigger: ReactNode;
  /** Accessible name for the trigger button. */
  label: string;
  triggerClassName?: string;
  children: ReactNode;
}

/**
 * Minimal click-toggled popover (Sonarr uses these for status detail). Headless
 * and token-styled: opens below the trigger, closes on Escape, outside click,
 * or re-click. Used for import_pending/import_blocked reasons (FRG-UI-006) and
 * verbatim rejection lists (FRG-UI-007).
 */
export function Popover({ trigger, label, triggerClassName, children }: PopoverProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDocMouseDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  return (
    <span className={styles.root} ref={rootRef}>
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        className={
          triggerClassName ? `${styles.trigger} ${triggerClassName}` : styles.trigger
        }
        onClick={() => setOpen((o) => !o)}
      >
        {trigger}
      </button>
      {open && (
        <div id={panelId} role="dialog" aria-label={label} className={styles.panel}>
          {children}
        </div>
      )}
    </span>
  );
}
