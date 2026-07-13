import { LayersIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <LayersIcon size={18} />
    <LayersIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <LayersIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>LayersIcon</span>
  </div>
);
