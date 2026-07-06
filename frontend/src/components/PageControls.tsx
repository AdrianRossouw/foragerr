import styles from './PageControls.module.css';

export interface PageControlsProps {
  page: number;
  totalRecords: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}

/**
 * Shared prev/next page controls for the paged daily surfaces
 * (FRG-UI-010/011/017 — design decision 5). "Page x of y" derives from the
 * envelope's totalRecords; nothing renders for an empty result set (the
 * screens own their explicit empty states).
 */
export function PageControls({
  page,
  totalRecords,
  pageSize,
  onPageChange,
}: PageControlsProps) {
  if (totalRecords <= 0) return null;
  const totalPages = Math.max(1, Math.ceil(totalRecords / pageSize));
  return (
    <nav className={styles.controls} aria-label="Pagination">
      <button
        type="button"
        className={styles.btn}
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
      >
        ‹ Prev
      </button>
      <span className={styles.label} data-testid="page-controls-label">
        Page {page} of {totalPages}
      </span>
      <button
        type="button"
        className={styles.btn}
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
      >
        Next ›
      </button>
    </nav>
  );
}
