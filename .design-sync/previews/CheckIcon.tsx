import { CheckIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <CheckIcon size={18} />
    <CheckIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <CheckIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>CheckIcon</span>
  </div>
);
