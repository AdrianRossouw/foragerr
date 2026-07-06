import type { ReactNode } from 'react';
import { Popover } from './Popover';
import styles from './decisionOverlay.module.css';

export interface ReasonsPopoverProps {
  /** Verbatim reasons, in the pipeline/comparator order — NEVER re-sorted. */
  reasons: readonly string[];
  /** Accessible name for both the trigger and the popover dialog. */
  label: string;
  /** Full class string for the decision chip that triggers the popover. */
  chipClassName: string;
  /** Trigger content, e.g. `<>! Blocked</>` or `<>! Rejected</>`. */
  chipContent: ReactNode;
  /** `ft-*` data-testid for the verbatim `<ul>` (e2e/SELECTORS.md contract). */
  listTestId: string;
}

/**
 * Shared reasons popover (FRG-UI-007 / FRG-UI-014) — the decision chip that,
 * when activated, reveals a candidate's rejection reasons VERBATIM in the order
 * the endpoint returned them. Both the interactive-search and manual-import
 * overlays render the identical Popover + list here so the two surfaces stay in
 * lockstep; callers supply only the chip styling/label and the `ft-*` list id.
 */
export function ReasonsPopover({
  reasons,
  label,
  chipClassName,
  chipContent,
  listTestId,
}: ReasonsPopoverProps) {
  return (
    <Popover trigger={<span className={chipClassName}>{chipContent}</span>} label={label}>
      {/* Verbatim reasons, one per line — never paraphrased or re-sorted. */}
      <ul className={styles.rejectionList} data-testid={listTestId}>
        {reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
    </Popover>
  );
}
