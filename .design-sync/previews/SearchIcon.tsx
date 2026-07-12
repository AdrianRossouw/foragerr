import { SearchIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <SearchIcon size={18} />
    <SearchIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <SearchIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>SearchIcon</span>
  </div>
);
