import type { ReviewGroup } from './reviewGroups';
import styles from './sources.module.css';

/**
 * The header of a collapsed (or expanded) same-title run (FRG-UI-029).
 *
 * It carries everything a collapse must not hide: how many rows it stands for,
 * the counts of their review statuses, and any failed download inside it. The
 * checkbox selects/deselects the whole group (it routes through the SAME
 * index-based `onSelectRow` the rows use, so shift-range spans headers and
 * rows coherently); the caret expands in place, and expanding reaches every
 * member's full actions.
 */
export function EntitlementGroupHeader({
  group,
  index,
  collapsed,
  selected,
  partiallySelected,
  onSelectRow,
  onToggleCollapse,
}: {
  group: ReviewGroup;
  /** Index in the FLAT review-item array (shared with the rows). */
  index: number;
  collapsed: boolean;
  /** Every member selected. */
  selected: boolean;
  /** Some but not all members selected. */
  partiallySelected: boolean;
  onSelectRow: (index: number, shiftKey: boolean) => void;
  onToggleCollapse: () => void;
}) {
  const { counts } = group;
  const statusBits = [
    counts.new > 0 ? `${counts.new} new` : null,
    counts.matched > 0 ? `${counts.matched} matched` : null,
    counts.ignored > 0 ? `${counts.ignored} ignored` : null,
  ].filter(Boolean) as string[];

  return (
    <div
      className={styles.groupHeader}
      data-testid={`group-header-${group.key}`}
      data-collapsed={collapsed ? 'true' : 'false'}
      data-rows={group.rows.length}
    >
      <input
        type="checkbox"
        className={styles.checkbox}
        checked={selected}
        ref={(el) => {
          // Mixed selection reads as indeterminate rather than as "none".
          if (el) el.indeterminate = !selected && partiallySelected;
        }}
        aria-label={`Select all ${group.rows.length} items in ${group.title}`}
        onChange={() => {}}
        onClick={(e) => onSelectRow(index, e.shiftKey)}
        data-testid={`group-select-${group.key}`}
      />
      <span className={styles.groupStack} aria-hidden>
        <i className="fa-solid fa-layer-group" />
      </span>
      <div className={styles.rowMain}>
        <div className={styles.rowTitle}>
          <span className={styles.rowName}>{group.title}</span>
          <span className={styles.groupCount} data-testid={`group-count-${group.key}`}>
            {group.rows.length} items
          </span>
        </div>
        <div className={styles.rowSub} data-testid={`group-statuses-${group.key}`}>
          {statusBits.join(' · ')}
          {counts.failed > 0 && (
            <span className={styles.groupFailed}>
              {statusBits.length > 0 ? ' · ' : ''}
              {counts.failed} failed download
              {counts.failed === 1 ? '' : 's'}
            </span>
          )}
          {group.bundle && (
            <span className={styles.bundleName}> · {group.bundle}</span>
          )}
        </div>
      </div>
      <button
        type="button"
        className={styles.linkBtn}
        aria-expanded={!collapsed}
        onClick={onToggleCollapse}
        data-testid={`group-toggle-${group.key}`}
      >
        {collapsed ? `Show ${group.rows.length}` : 'Collapse'}
      </button>
      <button
        type="button"
        className={styles.caret}
        aria-label={collapsed ? `Expand ${group.title}` : `Collapse ${group.title}`}
        aria-expanded={!collapsed}
        onClick={onToggleCollapse}
        tabIndex={-1}
      >
        <i className={`fa-solid ${collapsed ? 'fa-chevron-down' : 'fa-chevron-up'}`} />
      </button>
    </div>
  );
}
