import { TableIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <TableIcon size={18} />
    <TableIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <TableIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>TableIcon</span>
  </div>
);
