import { TrashIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <TrashIcon size={18} />
    <TrashIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <TrashIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>TrashIcon</span>
  </div>
);
