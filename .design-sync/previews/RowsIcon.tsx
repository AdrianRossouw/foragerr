import { RowsIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <RowsIcon size={18} />
    <RowsIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <RowsIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>RowsIcon</span>
  </div>
);
