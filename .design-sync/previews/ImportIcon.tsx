import { ImportIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <ImportIcon size={18} />
    <ImportIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <ImportIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>ImportIcon</span>
  </div>
);
