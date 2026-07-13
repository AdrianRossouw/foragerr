import { BookmarkIcon } from 'foragerr-frontend';

export const Sizes = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <BookmarkIcon size={18} />
    <BookmarkIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <BookmarkIcon size={32} />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>BookmarkIcon</span>
  </div>
);

/** Unfilled = unmonitored, filled = the "Wanted" state glyph (see CalendarScreen). */
export const States = () => (
  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
    <BookmarkIcon size={24} />
    <span style={{ color: 'var(--color-accent)' }}>
      <BookmarkIcon size={24} filled />
    </span>
    <span style={{ fontSize: 12, color: 'var(--text-secondary, #aaa)' }}>
      unfilled vs filled (wanted)
    </span>
  </div>
);
