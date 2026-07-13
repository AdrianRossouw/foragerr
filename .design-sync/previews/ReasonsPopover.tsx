import { useEffect, useRef, type ReactNode } from 'react';
import { ReasonsPopover } from 'foragerr-frontend';

/**
 * ReasonsPopover wraps Popover, so it opens on a trigger click and holds its own
 * state. To capture the OPEN reasons list statically, mount inside a stage that
 * clicks the decision chip once on mount.
 */
const OpenStage = ({ children, height = 260 }: { children: ReactNode; height?: number }) => {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>('button')?.click();
  }, []);
  return (
    <div ref={ref} style={{ position: 'relative', height }}>
      {children}
    </div>
  );
};

/** A blocked manual-import row exposing its verbatim reasons, open. */
export const Blocked = () => (
  <OpenStage>
    <ReasonsPopover
      label="saga-055.cbz — show reasons"
      chipClassName="chip"
      chipContent={<span style={{ color: 'var(--color-danger, #e05050)' }}>! Blocked</span>}
      listTestId="ft-manual-rejections-saga-055.cbz"
      reasons={[
        'Series unmonitored',
        'No series match for parsed title',
        'Unmapped issue number',
      ]}
    />
  </OpenStage>
);

/** A rejected search candidate with quality/cutoff reasons, open. */
export const Rejected = () => (
  <OpenStage>
    <ReasonsPopover
      label="Rejected — show reasons"
      chipClassName="chip"
      chipContent={<span style={{ color: 'var(--color-danger, #e05050)' }}>! Rejected</span>}
      listTestId="ft-rejections-guid-1"
      reasons={[
        'Issue before cutoff',
        'Below minimum size',
        'Language not in the wanted list',
      ]}
    />
  </OpenStage>
);

/** A single-reason case (the common minimal decision). */
export const SingleReason = () => (
  <OpenStage>
    <ReasonsPopover
      label="Skipped — show reasons"
      chipClassName="chip"
      chipContent={<span style={{ color: 'var(--text-muted, #888)' }}>Skipped</span>}
      listTestId="ft-rejections-guid-2"
      reasons={['Already downloaded']}
    />
  </OpenStage>
);
