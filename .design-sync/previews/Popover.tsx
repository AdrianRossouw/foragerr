import { useEffect, useRef, type ReactNode } from 'react';
import { Popover } from 'foragerr-frontend';

/**
 * Popover holds its open state internally and toggles on a trigger click. To
 * show the OPEN state statically, mount inside a stage that programmatically
 * clicks the trigger button once. A `.click()` fires a `click` event (not the
 * `mousedown` the outside-close handler listens for), so it opens and stays open.
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

/** A status chip whose popover reveals a short detail, shown open. */
export const StatusDetail = () => (
  <OpenStage>
    <Popover
      label="Import status detail"
      trigger={
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '2px 10px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--color-warning, #d0a020)',
            color: 'var(--color-warning, #d0a020)',
            fontSize: 13,
          }}
        >
          Pending
        </span>
      }
    >
      <div style={{ fontWeight: 500, marginBottom: 4 }}>Awaiting file move</div>
      <div style={{ color: 'var(--text-secondary, #aaa)' }}>
        Saga #55 downloaded; queued for import into the library folder.
      </div>
    </Popover>
  </OpenStage>
);

/** Popover carrying a small list of detail lines. */
export const DetailList = () => (
  <OpenStage>
    <Popover
      label="Match detail"
      trigger={
        <span
          style={{
            display: 'inline-flex',
            padding: '2px 10px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--surface-border)',
            color: 'var(--text-primary)',
            fontSize: 13,
          }}
        >
          Matched
        </span>
      }
    >
      <ul style={{ margin: 0, paddingLeft: 16, display: 'flex', flexDirection: 'column', gap: 4 }}>
        <li>Series: Monstress (2015)</li>
        <li>Issue: 44</li>
        <li>Source: DogNZB</li>
      </ul>
    </Popover>
  </OpenStage>
);
