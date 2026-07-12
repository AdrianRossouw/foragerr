import { LogoMarkIcon } from 'foragerr-frontend';

/** The brand mark at the sizes used in the sidebar/header lockup. */
export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <LogoMarkIcon size={18} />
    <LogoMarkIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <LogoMarkIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>LogoMarkIcon</span>
  </div>
);
