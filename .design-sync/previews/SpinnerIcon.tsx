import { SpinnerIcon } from 'foragerr-frontend';

/** The "downloading" state glyph (see CalendarScreen's StateGlyph). */
export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <SpinnerIcon size={18} />
    <SpinnerIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <SpinnerIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>SpinnerIcon</span>
  </div>
);
