import { PersonIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <PersonIcon size={18} />
    <PersonIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <PersonIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>PersonIcon</span>
  </div>
);
