/*
 * Publisher and format-chip palettes (FRG-UI-002, design decision 1).
 *
 * The owner's design tints cover art placeholders by publisher and colors
 * calendar spines / format chips. These are DATA — looked up per publisher or
 * per collected-edition format at render time — so they live here as exported
 * maps feeding inline styles, NOT as per-publisher CSS classes and NOT as CSS
 * variables in `tokens.css` (which stays the single source for the core
 * surface/accent/status palette). This module is the single source for the
 * publisher/format palette values; components import from here rather than
 * hardcoding a hex.
 */

/** Card/cover background tint shown before ComicVine art loads. */
export const PUBLISHER_TINT: Record<string, string> = {
  Marvel: '#3a2626',
  DC: '#26303c',
  Image: '#2b2b2b',
  'BOOM!': '#3a3124',
  Vertigo: '#2f2638',
  'Dark Horse': '#243030',
  'Cartoon Books': '#26332b',
  IDW: '#2b2b2b',
};

/** Accent used for calendar spines / publisher bars. */
export const PUBLISHER_ACCENT: Record<string, string> = {
  Marvel: '#c0555a',
  DC: '#5a86c0',
  Image: '#9a9a9a',
  'BOOM!': '#c9a24a',
  Vertigo: '#9a6fc0',
  'Dark Horse': '#5aa38f',
  'Cartoon Books': '#6fb87a',
  IDW: '#8a8a8a',
};

/** Fallback tint/accent for an unknown or null publisher. */
export const PUBLISHER_TINT_DEFAULT = '#2b2b2b';
export const PUBLISHER_ACCENT_DEFAULT = '#57b877';

/** A collected-edition format chip's background + text color. */
export interface FormatChipColor {
  bg: string;
  text: string;
}

/**
 * Format-chip palette keyed by the collected-edition book-type family: trade
 * paperbacks read blue, deluxe/hardcover amber, omnibus green. `booktype`
 * values (`tpb`/`gn`/`hc`/`one_shot`) map onto these three families.
 */
export const FORMAT_CHIP: Record<string, FormatChipColor> = {
  tpb: { bg: 'rgba(93, 156, 236, 0.16)', text: '#8ab6f0' },
  gn: { bg: 'rgba(93, 156, 236, 0.16)', text: '#8ab6f0' },
  hc: { bg: 'rgba(198, 132, 66, 0.18)', text: '#d99a5b' },
  omnibus: { bg: 'rgba(87, 184, 119, 0.18)', text: '#7fce9a' },
};

/**
 * Creator role chip palette keyed by the FIXED normalized-role vocabulary
 * (FRG-CRTR-001: writer/artist/penciler/inker/colorist/letterer/cover/editor/
 * other). Like FORMAT_CHIP these are DATA — a per-role tint+text looked up at
 * render time and fed into inline styles — so they live here beside the
 * publisher/format maps, not as CSS tokens. Each role gets a distinct low-alpha
 * wash + a legible text tone so a card's role chips read apart at a glance.
 */
export const ROLE_CHIP: Record<string, FormatChipColor> = {
  writer: { bg: 'rgba(93, 156, 236, 0.16)', text: '#8ab6f0' },
  artist: { bg: 'rgba(155, 111, 192, 0.18)', text: '#b892d8' },
  penciler: { bg: 'rgba(87, 184, 119, 0.16)', text: '#7fce9a' },
  inker: { bg: 'rgba(90, 134, 192, 0.16)', text: '#8fb2d8' },
  colorist: { bg: 'rgba(229, 165, 75, 0.18)', text: '#e0b06a' },
  letterer: { bg: 'rgba(201, 122, 168, 0.18)', text: '#d69ac2' },
  cover: { bg: 'rgba(90, 163, 143, 0.18)', text: '#7fc4b0' },
  editor: { bg: 'rgba(154, 154, 154, 0.16)', text: '#bcbcbc' },
  other: { bg: 'rgba(122, 122, 122, 0.16)', text: '#a4a4a4' },
};

/** Resolve a role's chip colors, falling back to the neutral "other" slot. */
export function roleChip(role: string): FormatChipColor {
  return ROLE_CHIP[role] ?? ROLE_CHIP.other;
}

/**
 * Corporate suffix words folded off a publisher name before the palette lookup
 * (FRG-UI-042). Feeds deliver "Marvel Comics" / "BOOM! Studios" / "IDW
 * Publishing" where the palette is keyed by the imprint alone, so an
 * exact-match lookup resolves nothing on real data.
 *
 * The list is deliberately short and holds only words that carry no identity of
 * their own. "Press" is excluded: it is identity-bearing — folding it collapses
 * "Oni Press" and "Kobold Press" onto names their publishers do not use.
 */
const CORPORATE_SUFFIXES = new Set([
  'comics',
  'studios',
  'entertainment',
  'publishing',
  'productions',
]);

/**
 * Fold trailing corporate suffixes off a publisher name. TRAILING only: the
 * words are suffixes, and stripping them mid-name would rewrite an imprint
 * whose own title contains one. A name made of nothing but suffix words keeps
 * its whole self rather than folding away to nothing.
 */
function foldCorporateSuffixes(name: string): string {
  const words = name.split(/\s+/);
  while (words.length > 1 && CORPORATE_SUFFIXES.has(words[words.length - 1].toLowerCase())) {
    words.pop();
  }
  return words.join(' ');
}

/**
 * Case-insensitive index over the named maps, so "dc comics" finds "DC". Built
 * from the union of both maps: a key present in only one of them still has to
 * resolve to its canonical casing, or that map's entry becomes unreachable.
 */
const NAMED_KEYS = new Map(
  [...Object.keys(PUBLISHER_TINT), ...Object.keys(PUBLISHER_ACCENT)].map((key) => [
    key.toLowerCase(),
    key,
  ]),
);

/**
 * The publisher's palette identity: the named palette's own key when the
 * normalized name matches one, otherwise the normalized name itself. This is
 * also what the Calendar's publisher chip prints, so the label and the color
 * always answer to the same string.
 */
export function publisherKey(publisher: string | null | undefined): string | null {
  const trimmed = publisher?.trim();
  if (!trimmed) return null;
  const folded = foldCorporateSuffixes(trimmed);
  return NAMED_KEYS.get(folded.toLowerCase()) ?? folded;
}

/**
 * The brand accent's hue, and the arc around it a derived hue may never land
 * in. A publisher outside the named palette must be distinguishable from the
 * app's own accent (FRG-UI-042) — a hash that happened to land on green would
 * read as "foragerr", not as a publisher.
 */
const BRAND_HUE = 140;
const BRAND_HUE_GUARD = 15;

/**
 * FNV-1a over the normalized name: a derived hue must be STABLE — the same
 * publisher takes the same color on every surface and across reloads — so the
 * hash may not depend on insertion order, list position, or anything but the
 * name itself.
 */
function stableHue(key: string): number {
  // Casefolded, because the named lookup is: a feed that switches to
  // "TITAN COMICS" mid-week must not repaint the publisher.
  const seed = key.toLowerCase();
  let hash = 2166136261;
  for (let i = 0; i < seed.length; i += 1) {
    hash ^= seed.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  const arc = 360 - 2 * BRAND_HUE_GUARD;
  return (BRAND_HUE + BRAND_HUE_GUARD + ((hash >>> 0) % arc)) % 360;
}

/*
 * Saturation/lightness bands for derived colors, fixed so a derived pair sits
 * at the same weight as the named palette on the dark shell: the accent reads
 * against the page at text weight, the tint stays a background wash a cover can
 * letterbox onto. Only the hue varies — the bands are what keep 300 unknown
 * publishers from rendering as 300 different intensities.
 */
const DERIVED_ACCENT_SATURATION = 38;
const DERIVED_ACCENT_LIGHTNESS = 62;
const DERIVED_TINT_SATURATION = 20;
const DERIVED_TINT_LIGHTNESS = 17;

/** Resolve a publisher's cover tint, deriving a stable one when unnamed. */
export function publisherTint(publisher: string | null | undefined): string {
  const key = publisherKey(publisher);
  if (key === null) return PUBLISHER_TINT_DEFAULT;
  const named = PUBLISHER_TINT[key];
  if (named !== undefined) return named;
  return `hsl(${stableHue(key)} ${DERIVED_TINT_SATURATION}% ${DERIVED_TINT_LIGHTNESS}%)`;
}

/**
 * Resolve a publisher's spine/bar accent. A named publisher takes its palette
 * accent, an unnamed one a stable derived hue, and only a null publisher falls
 * back to the brand green — a real publisher drawn in the brand accent is the
 * defect this resolution exists to end.
 */
export function publisherAccent(publisher: string | null | undefined): string {
  const key = publisherKey(publisher);
  if (key === null) return PUBLISHER_ACCENT_DEFAULT;
  const named = PUBLISHER_ACCENT[key];
  if (named !== undefined) return named;
  return `hsl(${stableHue(key)} ${DERIVED_ACCENT_SATURATION}% ${DERIVED_ACCENT_LIGHTNESS}%)`;
}
