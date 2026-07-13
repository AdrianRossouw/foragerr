import { GridIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <GridIcon size={18} />
    <GridIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <GridIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>GridIcon</span>
  </div>
);
