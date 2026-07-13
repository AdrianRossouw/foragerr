import { BookTypeBadge } from 'foragerr-frontend';

/** Every collected-edition book-type badge, as they'd appear on a series card. */
export const AllTypes = () => (
  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
    <BookTypeBadge booktype="tpb" />
    <BookTypeBadge booktype="gn" />
    <BookTypeBadge booktype="hc" />
    <BookTypeBadge booktype="one_shot" />
  </div>
);

/** A null booktype (ordinary single-issues run) renders nothing — shown next to a
 * labeled sibling so the empty render is visibly intentional, not a missing screenshot. */
export const NoBadge = () => (
  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
    <span style={{ color: 'var(--color-text-muted, #9a9a9a)', fontSize: 13 }}>
      Saga (ongoing series):
    </span>
    <BookTypeBadge booktype={null} />
  </div>
);

/** In context on a series title row. */
export const OnSeriesRow = () => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      <span>Monstress, Vol. 1: Awakening</span>
      <BookTypeBadge booktype="tpb" />
    </div>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      <span>The Department of Truth</span>
      <BookTypeBadge booktype={null} />
    </div>
  </div>
);
