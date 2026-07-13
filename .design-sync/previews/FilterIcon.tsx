import { FilterIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <FilterIcon size={18} />
    <FilterIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <FilterIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>FilterIcon</span>
  </div>
);
