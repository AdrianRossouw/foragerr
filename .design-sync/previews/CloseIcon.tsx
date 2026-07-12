import { CloseIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <CloseIcon size={18} />
    <CloseIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <CloseIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>CloseIcon</span>
  </div>
);
