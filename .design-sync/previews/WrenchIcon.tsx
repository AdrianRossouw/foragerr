import { WrenchIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <WrenchIcon size={18} />
    <WrenchIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <WrenchIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>WrenchIcon</span>
  </div>
);
