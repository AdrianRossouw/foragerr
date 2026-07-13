import { Poster } from 'foragerr-frontend';

const COVER_SVG =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="360">
      <rect width="240" height="360" fill="#4a2a2a"/>
      <rect y="280" width="240" height="80" fill="#1c1c1c"/>
      <text x="20" y="320" fill="#fff" font-family="sans-serif" font-size="26" font-weight="bold">SAGA</text>
      <text x="20" y="345" fill="#e8b23a" font-family="sans-serif" font-size="16">#1</text>
    </svg>`
  );

const frame = { width: 140, aspectRatio: '2 / 3', borderRadius: 6, overflow: 'hidden' as const };

/** A loaded cover next to the publisher-tint placeholder (no src). */
export const LoadedVsPlaceholder = () => (
  <div style={{ display: 'flex', gap: 16 }}>
    <div style={frame}>
      <Poster initial="S" src={COVER_SVG} alt="Saga #1 cover" />
    </div>
    <div style={frame}>
      <Poster initial="M" tint="#3a2626" alt="Monstress #1 cover" />
    </div>
  </div>
);

/** Publisher tints across the placeholder set — the honest static render before
 * ComicVine art loads. */
export const PublisherTints = () => (
  <div style={{ display: 'flex', gap: 12 }}>
    <div style={frame}>
      <Poster initial="X" tint="#3a2626" alt="Marvel title placeholder" />
    </div>
    <div style={frame}>
      <Poster initial="B" tint="#26303c" alt="DC title placeholder" />
    </div>
    <div style={frame}>
      <Poster initial="I" tint="#2b2b2b" alt="Image title placeholder" />
    </div>
    <div style={frame}>
      <Poster initial="L" tint="#2f2638" alt="Vertigo title placeholder" />
    </div>
  </div>
);

/** With the diagonal-stripe overlay texture, as used on poster cards. */
export const WithOverlay = () => (
  <div style={{ display: 'flex', gap: 16 }}>
    <div style={frame}>
      <Poster initial="D" tint="#243030" alt="Dark Horse title placeholder" overlay />
    </div>
    <div style={frame}>
      <Poster initial="S" src={COVER_SVG} alt="Saga #1 cover" overlay />
    </div>
  </div>
);
