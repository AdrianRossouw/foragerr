import { useState, type ReactNode } from 'react';
import { Menu, CheckIcon, SortIcon, FilterIcon, SlidersIcon } from 'foragerr-frontend';

/** Reserve vertical room so the absolutely-positioned open panel isn't clipped. */
const Stage = ({ children }: { children: ReactNode }) => (
  <div style={{ position: 'relative', height: 300 }}>{children}</div>
);

/** A menu row in the Sort/Filter style: a check when active, a label, optional count. */
const CheckRow = ({
  label,
  active,
  count,
}: {
  label: string;
  active?: boolean;
  count?: number;
}) => (
  <button
    type="button"
    data-menuitem
    style={{
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      width: '100%',
      padding: '6px 10px',
      background: 'none',
      border: 'none',
      borderRadius: 'var(--radius-sm)',
      color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
      font: 'inherit',
      textAlign: 'left',
      cursor: 'pointer',
    }}
  >
    <span style={{ width: 16, display: 'inline-flex', color: 'var(--color-accent)' }}>
      {active ? <CheckIcon size={14} /> : null}
    </span>
    <span style={{ flex: 1 }}>{label}</span>
    {count != null && (
      <span style={{ fontSize: 12, color: 'var(--text-muted, #888)' }}>{count}</span>
    )}
  </button>
);

/** The library "Sort" menu, open, with the active key checked. */
export const SortMenu = () => {
  const [open, setOpen] = useState(true);
  return (
    <Stage>
      <Menu open={open} onOpenChange={setOpen} label="Sort" icon={<SortIcon size={16} />} align="start">
        <CheckRow label="Title" active />
        <CheckRow label="Publisher" />
        <CheckRow label="Issues owned" />
        <CheckRow label="Date added" />
      </Menu>
    </Stage>
  );
};

/** The "Filter" menu with per-status counts, open. */
export const FilterMenu = () => {
  const [open, setOpen] = useState(true);
  return (
    <Stage>
      <Menu open={open} onOpenChange={setOpen} label="Filter" icon={<FilterIcon size={16} />} align="start">
        <CheckRow label="All" active count={128} />
        <CheckRow label="Monitored" count={94} />
        <CheckRow label="Missing issues" count={31} />
        <CheckRow label="Unmonitored" count={34} />
      </Menu>
    </Stage>
  );
};

/** The "Options" menu as a group panel (non-menuitem controls). */
export const OptionsMenu = () => {
  const [open, setOpen] = useState(true);
  return (
    <Stage>
      <Menu
        open={open}
        onOpenChange={setOpen}
        label="Options"
        icon={<SlidersIcon size={16} />}
        align="start"
        panelRole="group"
      >
        <div style={{ fontSize: 11, letterSpacing: '0.04em', color: 'var(--text-muted, #888)', padding: '4px 10px' }}>
          POSTER SIZE
        </div>
        <div style={{ display: 'flex', gap: 6, padding: '2px 10px 8px' }}>
          {['S', 'M', 'L'].map((s) => (
            <span
              key={s}
              style={{
                padding: '3px 12px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--surface-border)',
                background: s === 'M' ? 'var(--surface-card-hover)' : 'transparent',
                color: s === 'M' ? 'var(--text-primary)' : 'var(--text-secondary)',
                fontSize: 13,
              }}
            >
              {s}
            </span>
          ))}
        </div>
        <div style={{ height: 1, background: 'var(--surface-border)', margin: '4px 0' }} />
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 10px' }}>
          <span>Group volumes</span>
          <span style={{ fontSize: 12, color: 'var(--text-muted, #888)' }}>off</span>
        </div>
      </Menu>
    </Stage>
  );
};

/** Closed trigger with the disabled state (e.g. sort locked while grouped). */
export const DisabledTrigger = () => (
  <div style={{ display: 'flex', gap: 16 }}>
    <Menu open={false} onOpenChange={() => {}} label="Sort" icon={<SortIcon size={16} />} disabled>
      <div />
    </Menu>
  </div>
);
