import { useEffect, useRef, type ReactNode } from 'react';
import styles from './Menu.module.css';

/**
 * Shared raised dropdown menu (FRG-UI-003, design decision 2). A toolbar
 * trigger button plus a raised panel (design: bg `--surface-menu`, 1px border,
 * `--shadow-menu`). Controlled `open`/`onOpenChange` so a screen can enforce
 * one-menu-at-a-time and close every menu on a content-region click.
 *
 * Accessibility (design decision, risks): even though the design only shows
 * mouse flows, the menu is keyboard-reachable — Escape closes and returns focus
 * to the trigger, and Arrow Up/Down move focus between the panel's menu items
 * (any focusable element carrying `data-menuitem`). Opening focuses the first
 * item. Outside pointer-down closes.
 */
export function Menu({
  open,
  onOpenChange,
  label,
  icon,
  children,
  align = 'end',
  testId,
  menuTestId,
  disabled = false,
  triggerTitle,
  panelRole = 'menu',
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  label: string;
  icon: ReactNode;
  children: ReactNode;
  /** Panel edge aligned to the trigger. */
  align?: 'start' | 'end';
  /** data-testid for the trigger button. */
  testId?: string;
  /** data-testid for the panel. */
  menuTestId?: string;
  disabled?: boolean;
  /** Native tooltip on the trigger (e.g. explaining a disabled state). */
  triggerTitle?: string;
  /**
   * ARIA role for the panel. Default `menu` suits a list of menu items; pass
   * `group` when the panel holds non-menuitem controls (a radiogroup, a switch)
   * for which `menu` semantics would be invalid.
   */
  panelRole?: 'menu' | 'group';
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // Outside pointer-down + Escape close. Escape returns focus to the trigger so
  // keyboard users are not stranded in the (now-closed) panel.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        onOpenChange(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onOpenChange(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onOpenChange]);

  // Focus the first item when the panel opens. A `group` panel (or any panel
  // with no `[data-menuitem]`) has no menu items to land on, so fall back to the
  // first focusable control instead of leaving focus stranded on the trigger.
  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    if (!panel) return;
    const first = panel.querySelector<HTMLElement>('[data-menuitem]');
    if (first) {
      first.focus();
      return;
    }
    const focusable = panel.querySelector<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    focusable?.focus();
  }, [open]);

  const onPanelKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const items = Array.from(
      panelRef.current?.querySelectorAll<HTMLElement>('[data-menuitem]') ?? [],
    );
    if (items.length === 0) return;
    e.preventDefault();
    const current = document.activeElement as HTMLElement | null;
    const idx = current ? items.indexOf(current) : -1;
    const next =
      e.key === 'ArrowDown'
        ? items[(idx + 1 + items.length) % items.length]
        : items[(idx - 1 + items.length) % items.length];
    next?.focus();
  };

  return (
    <div className={styles.wrap} ref={wrapRef}>
      <button
        type="button"
        ref={triggerRef}
        className={open ? `${styles.trigger} ${styles.open}` : styles.trigger}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        title={triggerTitle}
        onClick={() => onOpenChange(!open)}
        data-testid={testId}
      >
        <span className={styles.icon}>{icon}</span>
        <span className={styles.label}>{label}</span>
      </button>
      {open && (
        <div
          ref={panelRef}
          role={panelRole}
          aria-label={label}
          className={styles.panel}
          data-align={align}
          data-testid={menuTestId}
          onKeyDown={onPanelKeyDown}
        >
          {children}
        </div>
      )}
    </div>
  );
}
