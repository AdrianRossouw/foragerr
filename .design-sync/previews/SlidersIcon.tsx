import { SlidersIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <SlidersIcon size={18} />
    <SlidersIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <SlidersIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>SlidersIcon</span>
  </div>
);
