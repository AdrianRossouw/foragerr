import { useEffect, type ReactNode } from 'react';
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

/**
 * Token-styled modal in the Sonarr school: dark chrome panel over a dimmed
 * backdrop, header title + close, scrollable body, optional footer actions.
 * Escape and backdrop-click close it.
 */
export function Modal({ title, label, onClose, children, footer, wide }: ModalProps) {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <div
      className={styles.backdrop}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
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
