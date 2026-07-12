import { SortIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <SortIcon size={18} />
    <SortIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <SortIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>SortIcon</span>
  </div>
);
