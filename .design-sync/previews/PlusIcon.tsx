import { PlusIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <PlusIcon size={18} />
    <PlusIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <PlusIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>PlusIcon</span>
  </div>
);
