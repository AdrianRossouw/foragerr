import { MoreIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <MoreIcon size={18} />
    <MoreIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <MoreIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>MoreIcon</span>
  </div>
);
