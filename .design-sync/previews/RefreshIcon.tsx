import { RefreshIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <RefreshIcon size={18} />
    <RefreshIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <RefreshIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>RefreshIcon</span>
  </div>
);
