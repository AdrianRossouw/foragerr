import { useEffect, useRef, type ReactNode } from 'react';
import styles from './Modal.module.css';

export interface ModalProps {
  title: ReactNode;
  /** Accessible dialog name (plain-text form of the title). */
  label: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  /** Full-width working-surface variant (interactive search). */
  wide?: boolean;
}

/** Every focusable element inside the panel, in document order. The selector
 * already excludes disabled controls and `tabindex="-1"`; no layout-based
 * visibility filter (jsdom reports every element as unlaid-out). */
function focusablesIn(panel: HTMLElement): HTMLElement[] {
  return Array.from(
    panel.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  );
}

/**
 * Token-styled modal in the Sonarr school: dark chrome panel over a dimmed
 * backdrop, header title + close, scrollable body, optional footer actions.
 * Escape and backdrop-click close it.
 *
 * Focus management (a11y): on open it moves focus to the first focusable inside
 * the panel, TRAPS Tab/Shift+Tab within the panel, and restores focus to the
 * element that was focused before it opened when it unmounts.
 */
export function Modal({ title, label, onClose, children, footer, wide }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  // Escape closes; Tab is trapped inside the panel.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;
      const panel = panelRef.current;
      if (!panel) return;
      const focusables = focusablesIn(panel);
      if (focusables.length === 0) {
        e.preventDefault();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && (active === first || !panel.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (active === last || !panel.contains(active))) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  // Focus the first focusable on open; restore the prior focus on close.
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    if (panel) {
      const focusables = focusablesIn(panel);
      (focusables[0] ?? panel).focus();
    }
    return () => previous?.focus?.();
  }, []);

  return (
    <div
      className={styles.backdrop}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className={wide ? styles.panelWide : styles.panel}
      >
        <header className={styles.header}>
          <span>{title}</span>
          <button
            type="button"
            className={styles.close}
            aria-label="Close"
            onClick={onClose}
          >
            ×
          </button>
        </header>
        <div className={styles.body}>{children}</div>
        {footer != null && <footer className={styles.footer}>{footer}</footer>}
      </div>
    </div>
  );
}
