import { InitialsAvatar } from 'foragerr-frontend';

/** Default size, a few real creator names to show the two-letter derivation. */
export const Default = () => (
  <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
    <InitialsAvatar name="Brian K. Vaughan" />
    <InitialsAvatar name="Marjorie Liu" />
    <InitialsAvatar name="Fiona Staples" />
    <InitialsAvatar name="Sana Takeda" />
  </div>
);

/** Size sweep — the avatar used at list-row scale up to a creator-page header. */
export const Sizes = () => (
  <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
    <InitialsAvatar name="James Tynion IV" size={28} />
    <InitialsAvatar name="James Tynion IV" size={46} />
    <InitialsAvatar name="James Tynion IV" size={72} />
  </div>
);

/** Single-word name falls back to its first two letters. */
export const SingleWordName = () => <InitialsAvatar name="Moebius" />;
