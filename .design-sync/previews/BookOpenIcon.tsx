import { BookOpenIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <BookOpenIcon size={18} />
    <BookOpenIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <BookOpenIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>BookOpenIcon</span>
  </div>
);
